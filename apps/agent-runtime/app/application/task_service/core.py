from __future__ import annotations

from app.observability import get_logger
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any


from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from app.context.manager import ContextManager
from app.domain.models import (
    AutoReviewModelMode,
    AutoReviewPolicy,
    ChapterDraft,
    DraftResult,
    ReviewPayload,
    SourceAsset,
    StoryPlan,
    TaskCreateRequest,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    TaskEvent,
    utc_now,
)
from app.graph.main_graph import (
    build_default_callbacks,
)
from app.workflow.callbacks import WorkflowCallbacks
from app.workflow.engine import NovelWorkflowEngine
from app.graph.supervisor_graph import build_initial_supervisor_plan
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import (
    StoryEngine,
)
from app.observability import RequestContext, request_id_var
from app.observability.context import push_request_flow
from app.observability.performance import log_performance, performance_span
from app.rag.service import RagService
from app.storage.db_repository import get_novel_project, update_project_status
from app.storage.task_store import TaskLogStore

logger = get_logger(__name__)


class TaskServiceCoreMixin:
    _STALE_RUN_AFTER = timedelta(minutes=10)

    def __init__(
        self,
        store: TaskLogStore,
        engine: StoryEngine,
        model_catalog: ModelCatalogService | None = None,
        context_manager: ContextManager | None = None,
        rag_service: RagService | None = None,
        novel_skill_service: Any | None = None,
        style_profile_service: Any | None = None,
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
        self.rag_service = rag_service
        self.novel_skill_service = novel_skill_service
        self.style_profile_service = style_profile_service
        self.auto_review = auto_review
        self.auto_review_policy = auto_review_policy or {}
        checkpoint_db_path = str(Path(self.store.root_dir) / "checkpoints.db")
        callbacks = build_default_callbacks(
            engine,
            context_manager=self.context_manager,
            model_catalog=self.model_catalog,
            rag_service=self.rag_service,
            novel_skill_service=self.novel_skill_service,
            style_profile_service=self.style_profile_service,
            auto_review=auto_review,
            auto_review_policy=self.auto_review_policy,
        )
        callbacks = self._guard_workflow_callbacks_for_stop(callbacks)
        self.workflow_engine = NovelWorkflowEngine(
            callbacks=callbacks,
            checkpoint_db_path=checkpoint_db_path,
        )
        self._active_runs: set[str] = set()
        self._run_lock = threading.Lock()
        self._chapter_file_locks: dict[str, threading.Lock] = {}
        self._active_threads: dict[str, threading.Thread] = {}
        self._stop_requested: set[str] = set()
        self._queued_continue_runs: set[str] = set()

        # 初始化 SQLite 业务数据库
        from app.storage.database import init_db
        configured_db_path = getattr(self.engine.settings, "database_path", None)
        db_path = Path(configured_db_path) if configured_db_path else Path(self.store.root_dir) / "data.db"
        init_db(str(db_path), settings=self.engine.settings)

    @property
    def graph(self):
        """向后兼容：旧代码与测试通过 graph 属性访问工作流引擎。"""
        return getattr(self, "workflow_engine", None)

    @graph.setter
    def graph(self, value):
        """允许外部注入 FakeGraph（测试兼容性）。

        若注入对象仅提供旧式 ``invoke`` 接口，自动包装为 ``NovelWorkflowEngine``
        兼容形态，使 ``start/resume/get_state/update_state`` 均可正常调用。
        """
        if value is None:
            logger.warning("workflow_engine 被设置为 None，后续依赖工作流引擎的操作可能失败。 caller=%s", type(self).__name__)
            self.workflow_engine = None
            return
        if all(hasattr(value, attr) for attr in ("start", "resume", "get_state", "update_state")):
            self.workflow_engine = value
            return

        class _FakeEngineAdapter:
            def __init__(self, _graph):
                self._graph = _graph

            def start(self, state, config=None):
                return self._graph.invoke(state, config=config)

            def resume(self, command, config=None):
                return self._graph.invoke(command, config=config)

            def get_state(self, config):
                if hasattr(self._graph, "get_state"):
                    return self._graph.get_state(config)
                from types import SimpleNamespace
                return SimpleNamespace(values={})

            def update_state(self, config, values, as_node=None):
                if hasattr(self._graph, "update_state"):
                    return self._graph.update_state(config, values, as_node=as_node)

        self.workflow_engine = _FakeEngineAdapter(value)

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        push_request_flow("service.create_task")
        requested_model = (payload.model_id or "").strip()
        if not requested_model:
            raise ValueError("请显式选择当前供应商返回的模型后再创建任务。")
        self.model_catalog.ensure_novel_generation_model_supported(requested_model)
        review_model_id = (payload.review_model_id or "").strip()
        if payload.auto_review_model_mode is AutoReviewModelMode.FIXED and review_model_id:
            self.model_catalog.ensure_novel_generation_model_supported(review_model_id)
        task = self.store.create_task(payload)
        task.supervisor_plan = build_initial_supervisor_plan(payload)
        resolved_auto_review = self._resolve_task_auto_review(task)
        task.auto_review = resolved_auto_review
        if resolved_auto_review and not task.auto_review_policy:
            task.auto_review_policy = dict(self.auto_review_policy)
        task = self.store.save(task)
        return self._sync_supervisor_plan(task.id)

    def _resolve_task_model_id(self, task: TaskRecord) -> str:
        candidate = (task.model_id or "").strip()
        if not candidate:
            raise ValueError("任务没有已选模型，请在本次动作中显式选择当前供应商返回的模型。")
        self.model_catalog.ensure_novel_generation_model_supported(candidate)
        return candidate

    def _resolve_action_model_id(self, task: TaskRecord, model_id: str | None) -> str:
        requested_model = (model_id or "").strip()
        if requested_model:
            self.model_catalog.ensure_novel_generation_model_supported(requested_model)
            return requested_model
        return self._resolve_task_model_id(task)

    def _resolve_auto_review_policy(
        self,
        task: TaskRecord,
        action_model_id: str | None = None,
        *,
        validate_models: bool = True,
        policy_source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy_dict = dict(policy_source) if policy_source is not None else dict(task.auto_review_policy or self.auto_review_policy or {})
        if task.auto_review_model_mode is not None:
            policy_dict["auto_review_model_mode"] = task.auto_review_model_mode.value
        if task.review_model_id:
            policy_dict["review_model_id"] = task.review_model_id

        resolved_model_id = self._resolve_action_model_id(task, action_model_id)
        mode = AutoReviewPolicy.model_validate(policy_dict).auto_review_model_mode
        if mode is AutoReviewModelMode.FOLLOW_CREATIVE:
            policy_dict["auditor_model"] = resolved_model_id
            policy_dict["synthesis_model"] = resolved_model_id
        else:
            fixed_model = str(policy_dict.get("review_model_id") or "").strip()
            if fixed_model:
                self.model_catalog.ensure_novel_generation_model_supported(fixed_model)
                policy_dict["auditor_model"] = fixed_model
                policy_dict["synthesis_model"] = fixed_model
            elif not str(policy_dict.get("auditor_model") or "").strip():
                policy_dict["auditor_model"] = resolved_model_id
            if not str(policy_dict.get("synthesis_model") or "").strip():
                policy_dict["synthesis_model"] = str(policy_dict.get("auditor_model") or resolved_model_id)
        policy = AutoReviewPolicy.model_validate(policy_dict)
        if validate_models and policy.auto_review_model_mode is AutoReviewModelMode.FIXED:
            checked_model_ids: set[str] = set()
            for configured_model_id in (policy.auditor_model, policy.synthesis_model):
                candidate = configured_model_id.strip()
                if candidate and candidate not in checked_model_ids:
                    self.model_catalog.ensure_novel_generation_model_supported(candidate)
                    checked_model_ids.add(candidate)
        return policy_dict

    def _auto_review_model_metadata(self, task: TaskRecord, action_model_id: str | None = None) -> dict[str, str]:
        creative_model_id = (action_model_id or task.model_id or "").strip()
        policy_dict = dict(task.auto_review_policy or self.auto_review_policy or {})
        if task.auto_review_model_mode is not None:
            policy_dict["auto_review_model_mode"] = task.auto_review_model_mode.value
        if task.review_model_id:
            policy_dict["review_model_id"] = task.review_model_id
        policy = AutoReviewPolicy.model_validate(policy_dict)
        if policy.auto_review_model_mode is AutoReviewModelMode.FOLLOW_CREATIVE:
            return {
                "auto_review_model_mode": AutoReviewModelMode.FOLLOW_CREATIVE.value,
                "review_model_id": creative_model_id,
            }
        return {
            "auto_review_model_mode": AutoReviewModelMode.FIXED.value,
            "review_model_id": (
                str(policy_dict.get("review_model_id") or "").strip()
                or policy.auditor_model
                or policy.synthesis_model
                or creative_model_id
            ),
        }

    def _with_model_id(self, payload: dict[str, Any], model_id: str) -> dict[str, Any]:
        next_payload = dict(payload)
        next_payload["model_id"] = model_id
        return next_payload

    def _record_last_action(self, task_id: str, *, model_id: str, kind: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.last_action_model_id == model_id and task.last_action_kind == kind:
            return task
        task.last_action_model_id = model_id
        task.last_action_kind = kind
        return self.store.save(task)

    def add_source(self, task_id: str, filename: str, media_type: str, content: str) -> TaskRecord:
        source = SourceAsset(filename=filename, media_type=media_type, content=content)
        return self.store.add_source(task_id, source)

    def get_task(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def cancel_task(self, task_id: str, comment: str = "") -> TaskRecord:
        """取消一个正在运行或等待审核的任务。"""
        push_request_flow("service.cancel_task")
        # 检查任务是否在活跃运行中，如果是则请求后台链路停止写入。
        with self._run_lock:
            was_active = task_id in self._active_runs
            thread = self._active_threads.get(task_id)
            if was_active:
                self._stop_requested.add(task_id)
        if thread is not None and thread.is_alive():
            logger.info("取消任务已发送停止信号，后台线程将自行收敛，task_id=%s", task_id)
        # 保存 blocked_from_status 以便后续恢复，并清理残留的活动批次
        from app.storage.db_repository import get_active_batch, get_novel_project, mark_batch_failed, update_project_status
        project = get_novel_project(task_id)
        if project is not None:
            current_status = project.status
            blocked = project.blocked_from_status or current_status
            if not project.blocked_from_status:
                update_project_status(
                    task_id,
                    status=current_status,
                    blocked_from_status=blocked,
                )
            active_batch = get_active_batch(task_id)
            if active_batch is not None:
                mark_batch_failed(task_id, int(active_batch.batch_no))
            update_project_status(
                task_id,
                status=current_status,
                active_batch_no=None,
                active_continue_request_id="",
                blocked_from_status=blocked,
            )
        record = self.store.cancel_task(task_id, comment=comment)
        self._sync_supervisor_plan(task_id)
        return record

    def delete_task(self, task_id: str) -> dict[str, str]:
        """删除一个已取消/已完成/失败的任务（不能删除运行中的任务）。"""
        push_request_flow("service.delete_task")
        # 再次确认任务不在活跃运行中
        with self._run_lock:
            if task_id in self._active_runs:
                if task_id in self._stop_requested:
                    raise ValueError("任务正在取消中，请等待后台线程结束后再删除。")
                raise ValueError("任务正在运行中，请先取消后再删除。")
        # 级联清理数据库关联记录
        self._delete_db_associations(task_id)
        result = self.store.delete_task(task_id)
        return result

    def _delete_db_associations(self, task_id: str) -> None:
        """删除任务的数据库关联记录。"""
        try:
            from app.storage.db_repository import delete_task_associations
            delete_task_associations(task_id)
        except Exception as exc:
            logger.exception("删除任务 %s 的数据库关联记录失败", task_id)
            raise RuntimeError(f"删除任务 {task_id} 的数据库关联记录失败") from exc

    def run_task(self, task_id: str, model_id: str | None = None) -> TaskRecord:
        push_request_flow("service.run_task")
        with self._run_lock:
            if task_id in self._active_runs:
                raise ValueError("任务正在运行中，请勿重复提交。")
        task = self.store.get(task_id)
        if task.status not in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED}:
            raise ValueError("只有新建任务或已上传素材的任务才能开始生成。")
        if self.rag_service is not None and not self.rag_service.is_ready():
            raise ValueError(self.rag_service.readiness_error())
        action_model_id = self._resolve_action_model_id(task, model_id)
        snapshot = self.store.mark_stage(
            task_id,
            status=TaskStatus.PLANNING,
            stage="planning",
            progress=max(task.progress, 5),
            message="任务已进入后台执行，正在整理创作要求。",
            event_type="task.queued",
        )
        snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="run")
        snapshot = self._sync_supervisor_plan(task_id)
        self._start_background(task_id, self._run_task_sync, task_id, action_model_id)
        return snapshot

    def _has_novel_project(self, task_id: str) -> bool:
        from app.storage.db_repository import get_novel_project

        return get_novel_project(task_id) is not None

    def _ensure_novel_project_seeded(self, task: TaskRecord) -> None:
        if task.story_plan is None:
            return
        from app.storage.db_repository import get_novel_project, seed_outline_chapters, upsert_novel_project

        if get_novel_project(task.id) is None:
            upsert_novel_project(task, task.story_plan)
        seed_outline_chapters(task.id, task.story_plan)

    def _sync_result(
        self,
        task_id: str,
        result: dict[str, Any],
        review_comment: str = "",
    ) -> TaskRecord:
        snapshot = self.workflow_engine.get_state(self._config(task_id))
        values = snapshot.values if snapshot and hasattr(snapshot, "values") else {}
        normalized_spec = values.get("normalized_spec")
        if normalized_spec:
            current_task = self.store.get(task_id)
            persisted_spec = self._persistable_normalized_spec(current_task, normalized_spec)
            if current_task.normalized_spec != persisted_spec:
                self.store.update_normalized_spec(task_id, persisted_spec)
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
            review = ReviewPayload.model_validate(self._extract_interrupt_payload(result))
            review_type = review.type
            auto_review_trace = values.get("auto_review_trace") or []
            # auto_review 异常降级时，state 中可能带有 review_comment，透传给用户
            review_comment = review_comment or values.get("review_comment", "")
            if review_comment:
                review.summary = review_comment

            if review_type == "outline_review":
                if not story_plan_data:
                    raise RuntimeError("工作流进入审核前未生成可用大纲。")
                story_plan = StoryPlan.model_validate(story_plan_data)
                record = self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="outline",
                    title="大纲已生成",
                    detail="已完成故事骨架与章节规划，等待人工审核。",
                    unit_id="outline",
                )
                return record

            if review_type == "window_draft_ready":
                if not story_plan_data:
                    raise RuntimeError("章节规划窗口暂停前未生成可用大纲。")
                story_plan = StoryPlan.model_validate(story_plan_data)
                planned_until = len(story_plan.chapter_plan)
                record = self.store.set_ready_for_batch(
                    task_id,
                    story_plan,
                    message=f"章节计划已确认至第 {planned_until} 章，等待继续创作。",
                )
                self._ensure_novel_project_seeded(record)
                project = get_novel_project(task_id)
                completed_count = int(project.completed_chapter_count or 0) if project is not None else 0
                update_project_status(
                    task_id,
                    status=TaskStatus.READY_FOR_BATCH.value,
                    completed_chapter_count=completed_count,
                    next_chapter_number=completed_count + 1,
                    active_batch_no=None,
                    active_continue_request_id="",
                    current_generating_chapter_number=None,
                )
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="outline",
                    title="章节规划窗口已就绪",
                    detail=f"已确认第 1-{planned_until} 章计划，等待正文生成。",
                    unit_id="outline-window",
                )
                return record

            elif review_type == "chapter_pair_review":
                current_chapter_pair = values.get("current_chapter_pair") or []
                # 补全缺失字段，防止旧 checkpoint 数据不完整导致验证失败
                def _normalize_chapter(ch: dict[str, Any]) -> dict[str, Any]:
                    return {
                        "number": ch.get("number") if ch.get("number") is not None else 0,
                        "title": ch.get("title") or "",
                        "summary": ch.get("summary") or "",
                        "content": ch.get("content") or "",
                    }
                review.chapter_pair = [ChapterDraft.model_validate(_normalize_chapter(ch)) for ch in current_chapter_pair]
                batch_index = values.get("batch_index", 0)
                completed = values.get("completed_chapters") or []
                chapter_plan = (story_plan_data or {}).get("chapter_plan") or []
                batch_end = min(batch_index + len(current_chapter_pair), len(chapter_plan))
                review.batch_index = batch_index
                review.completed_count = len(completed)
                review.total_chapters = len(chapter_plan)
                resolved_story_plan = StoryPlan.model_validate(story_plan_data) if story_plan_data else None
                record = self.store.set_waiting_chapter_review(task_id, review, auto_review_trace, story_plan=resolved_story_plan)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title="章节批次已生成",
                    detail=(
                        f"第 {batch_index + 1} 章已起草，等待审核。"
                        if batch_end <= batch_index + 1
                        else f"第 {batch_index + 1}-{batch_end} 章已起草，等待审核。"
                    ),
                    unit_id=f"chapter-pair-{batch_index}",
                )
                return record

            elif review_type == "verification_review":
                verification_report = values.get("verification_report") or {}
                review.verification_report = verification_report
                resolved_story_plan = StoryPlan.model_validate(story_plan_data) if story_plan_data else None
                record = self.store.set_waiting_verification_review(task_id, review, auto_review_trace, story_plan=resolved_story_plan)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
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
            record = self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
            return self._safe_sync_supervisor_plan(task_id, fallback=record)

        # 工作流正常结束
        story_plan_data = values.get("story_plan")
        if not story_plan_data:
            raise RuntimeError("工作流结束后未找到大纲结果。")
        story_plan = StoryPlan.model_validate(story_plan_data)
        if values.get("cancelled"):
            self.store.set_cancelled(task_id, story_plan, review_comment)
            return self._safe_sync_supervisor_plan(task_id, fallback=self.store.get(task_id))

        draft_result_data = values.get("draft_result")
        if not draft_result_data:
            raise RuntimeError("工作流结束后未找到正文结果。")
        draft_result = DraftResult.model_validate(draft_result_data)
        draft_result = self._rebuild_completed_draft_result_if_needed(
            task_id=task_id,
            story_plan=story_plan,
            draft_result=draft_result,
            normalized_spec=values.get("normalized_spec") if isinstance(values.get("normalized_spec"), dict) else {},
        )
        self._validate_completed_draft_result(story_plan, draft_result)
        artifacts = self._build_artifacts(story_plan, draft_result)
        auto_review_trace = values.get("auto_review_trace") or []
        record = self.store.set_completed(task_id, story_plan, draft_result, artifacts)
        if auto_review_trace:
            record.auto_review_trace = auto_review_trace
            record = self.store.save(record)
        record = self._safe_sync_supervisor_plan(task_id, fallback=record)
        self._safe_emit_trace_summary(
            task_id,
            kind="completed",
            title="正文生成完成",
            detail="章节已全部写完，正文与工件等待用户确认归档。",
        )
        return record

    def _rebuild_completed_draft_result_if_needed(
        self,
        *,
        task_id: str,
        story_plan: StoryPlan,
        draft_result: DraftResult,
        normalized_spec: dict[str, Any],
    ) -> DraftResult:
        planned_total = int(story_plan.planned_chapter_count or len(story_plan.chapter_plan) or 0)
        if planned_total <= 0:
            raise RuntimeError("正文完成前缺少有效章节计划。")

        current_chapters = self.get_current_chapters(task_id)
        if len(current_chapters) >= planned_total and len(current_chapters) > len(draft_result.chapters):
            chapters = current_chapters[:planned_total]
            return self._build_draft_result_from_chapters(
                story_plan=story_plan,
                chapters=chapters,
                normalized_spec=normalized_spec,
            )

        if len(draft_result.chapters) < planned_total:
            raise RuntimeError(
                f"正文结果章节数不足：当前 {len(draft_result.chapters)} 章，计划 {planned_total} 章。"
            )
        return draft_result

    @staticmethod
    def _validate_completed_draft_result(story_plan: StoryPlan, draft_result: DraftResult) -> None:
        planned_total = int(story_plan.planned_chapter_count or len(story_plan.chapter_plan) or 0)
        if planned_total <= 0:
            raise RuntimeError("正文完成前缺少有效章节计划。")
        if len(draft_result.chapters) != planned_total:
            raise RuntimeError(
                f"正文结果章节数不匹配：当前 {len(draft_result.chapters)} 章，计划 {planned_total} 章。"
            )
        for expected_number, chapter in enumerate(draft_result.chapters, start=1):
            if chapter.number != expected_number:
                raise RuntimeError("正文结果章节编号不连续，不能标记任务完成。")
            if not chapter.content.strip():
                raise RuntimeError(f"第 {expected_number} 章正文为空，不能标记任务完成。")

    def _build_draft_result_from_chapters(
        self,
        *,
        story_plan: StoryPlan,
        chapters: list[dict[str, Any]],
        normalized_spec: dict[str, Any],
    ) -> DraftResult:
        chapter_drafts = [
            ChapterDraft.model_validate(
                {
                    "number": chapter.get("number") if chapter.get("number") is not None else index + 1,
                    "title": chapter.get("title") or f"第{index + 1}章",
                    "summary": chapter.get("summary") or "",
                    "content": chapter.get("content") or "",
                }
            )
            for index, chapter in enumerate(chapters)
        ]
        if normalized_spec.get("mode") == "short_story" and len(chapter_drafts) <= 3:
            body = "\n\n".join(chapter.content for chapter in chapter_drafts)
        else:
            body = "\n\n".join(f"## {chapter.title}\n{chapter.content}" for chapter in chapter_drafts)
        return DraftResult(
            title=story_plan.working_title,
            summary=story_plan.logline,
            body=body,
            chapters=chapter_drafts,
        )

    def _persistable_normalized_spec(self, task: TaskRecord, normalized_spec: dict[str, Any]) -> dict[str, Any]:
        return self._with_model_id(normalized_spec, self._resolve_task_model_id(task))

    def _initial_state(self, task: TaskRecord, action_model_id: str | None = None) -> dict[str, Any]:
        reference_text = "\n\n".join(source.content for source in task.sources)
        resolved_auto_review = self._resolve_task_auto_review(task)
        resolved_model_id = self._resolve_action_model_id(task, action_model_id)
        auto_review_policy = self._resolve_auto_review_policy(
            task,
            action_model_id,
            validate_models=resolved_auto_review,
        )
        return {
            "task_id": task.id,
            "input_payload": {
                "mode": task.mode.value,
                "creative_mode": task.creative_mode.value if task.creative_mode else "",
                "novel_size": task.novel_size.value if task.novel_size else "",
                "target_chapter_count": (
                    task.target_chapter_count
                    if task.target_chapter_count is not None
                    else task.input.target_chapter_count
                ),
                "chapter_count_min": (
                    task.chapter_count_min
                    if task.chapter_count_min is not None
                    else task.input.chapter_count_min
                ),
                "chapter_count_max": (
                    task.chapter_count_max
                    if task.chapter_count_max is not None
                    else task.input.chapter_count_max
                ),
                "chapter_word_min": task.chapter_word_min or task.input.target_words,
                "model_id": resolved_model_id,
                "prompt": task.input.prompt,
                "genre": task.input.genre,
                "style": task.input.style,
                "style_profile_id": task.input.style_profile_id,
                "target_words": task.input.target_words,
                "audience": task.input.audience,
                "banned": task.input.banned,
                "title_hint": task.input.title_hint,
            },
            "reference_text": reference_text,
            "source_assets": [source.model_dump(mode="json") for source in task.sources],
            "auto_review": resolved_auto_review,
            "auto_review_policy": auto_review_policy,
        }

    def _resolve_task_auto_review(self, task: TaskRecord) -> bool:
        if task.auto_review is None:
            return self.auto_review
        return task.auto_review

    def _config(self, task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}, "recursion_limit": 100}

    def _graph_state_values(self, task_id: str) -> dict[str, Any]:
        try:
            snapshot = self.workflow_engine.get_state(self._config(task_id))
        except Exception:
            logger.warning("读取工作流 checkpoint 状态失败 task_id=%s", task_id, exc_info=True)
            return {}
        return snapshot.values if snapshot and hasattr(snapshot, "values") and isinstance(snapshot.values, dict) else {}

    def _sync_checkpoint_with_db(self, task_id: str) -> None:
        """checkpoint 状态与数据库状态对账，以数据库为准。"""
        if not hasattr(self.workflow_engine, "update_state"):
            return
        from app.storage.db_repository import get_novel_project
        project = get_novel_project(task_id)
        if project is None:
            return
        values = self._graph_state_values(task_id)
        if not values:
            return
        db_status = str(project.status or "")
        patch: dict[str, Any] = {}
        # 同步小说项目状态字段
        if db_status and values.get("novel_project_status") != db_status:
            patch["novel_project_status"] = db_status
        if project.completed_chapter_count is not None and values.get("completed_chapter_count") != project.completed_chapter_count:
            patch["completed_chapter_count"] = project.completed_chapter_count
        if project.next_chapter_number is not None and values.get("next_chapter_number") != project.next_chapter_number:
            patch["next_chapter_number"] = project.next_chapter_number
        if patch:
            logger.info("checkpoint 与数据库状态不一致，已同步: %s", patch)
            try:
                self.workflow_engine.update_state(self._config(task_id), patch)
            except Exception as exc:
                logger.warning("checkpoint 状态同步失败: %s", exc)

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

    def _safe_sync_supervisor_plan(self, task_id: str, *, fallback: TaskRecord) -> TaskRecord:
        try:
            return self._sync_supervisor_plan(task_id)
        except Exception:
            logger.exception("supervisor 计划同步失败，保留已持久化任务状态，task_id=%s", task_id)
            return self.store.get(task_id) if fallback.id == task_id else fallback

    def _safe_emit_trace_summary(self, task_id: str, **kwargs: Any) -> None:
        try:
            self._emit_trace_summary(task_id, **kwargs)
        except Exception:
            logger.exception("trace 摘要写入失败，已保留任务主状态，task_id=%s", task_id)

    def _has_stable_terminal_state(self, task: TaskRecord) -> bool:
        return task.status in {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        }

    def _mark_failed_unless_stable(self, task_id: str, message: str) -> TaskRecord:
        current = self.store.get(task_id)
        if self._is_stop_requested(task_id):
            return current
        recovered_completed = self._recover_completed_result_from_available_chapters(
            current,
            source="runtime_failure",
            failure_message=message,
        )
        if recovered_completed is not None:
            logger.warning(
                "后台异常发生时章节已完整落盘，已恢复为完成态。task_id=%s reason=%s",
                task_id,
                message,
            )
            return self._safe_sync_supervisor_plan(task_id, fallback=recovered_completed)
        if self._has_stable_terminal_state(current):
            logger.warning(
                "任务已进入稳定状态，跳过失败覆盖。task_id=%s status=%s reason=%s",
                task_id,
                current.status.value,
                message,
            )
            self.store.append_event(
                task_id,
                stage=current.current_stage or "unknown",
                message=f"后台异常（未覆盖状态）：{message}",
                event_type="task.error_recorded",
                payload={"detail": message, "status_at_error": current.status.value},
            )
            return current
        if (
            current.story_plan is not None
            or current.pending_review is not None
            or current.normalized_spec
            or self._has_novel_project(task_id)
            or bool(str(current.input.prompt or "").strip())
        ):
            record = self.store.set_waiting_manual_action(
                task_id,
                message,
                payload={
                    "summary": "任务执行异常，但存在可恢复上下文，已转入待人工处理。",
                    "display_level": "public",
                    "reason": "recoverable_runtime_error",
                },
            )
            project = get_novel_project(task_id)
            if project is not None:
                update_project_status(
                    task_id,
                    status=TaskStatus.WAITING_MANUAL_ACTION.value,
                    blocked_from_status=project.status,
                )
            return self._safe_sync_supervisor_plan(task_id, fallback=record)
        record = self.store.set_failed(task_id, message)
        return self._safe_sync_supervisor_plan(task_id, fallback=record)

    def _enter_active_run(self, task_id: str) -> bool:
        with self._run_lock:
            if task_id in self._active_runs:
                return False
            self._active_runs.add(task_id)
            return True

    def _leave_active_run(self, task_id: str) -> None:
        with self._run_lock:
            self._active_runs.discard(task_id)
            self._active_threads.pop(task_id, None)
            self._stop_requested.discard(task_id)

    def _is_stop_requested(self, task_id: str) -> bool:
        with self._run_lock:
            return task_id in self._stop_requested

    def _guard_workflow_callbacks_for_stop(self, callbacks: WorkflowCallbacks) -> WorkflowCallbacks:
        guarded: dict[str, Any] = {}

        def cancelled_patch(state: dict[str, Any]) -> dict[str, Any]:
            patch: dict[str, Any] = {"cancelled": True}
            review_comment = state.get("review_comment")
            if review_comment:
                patch["review_comment"] = review_comment
            return patch

        def wrap(callback):
            def guarded_callback(state: dict[str, Any]) -> dict[str, Any]:
                task_id = str(state.get("task_id") or "")
                if task_id and self._is_stop_requested(task_id):
                    return cancelled_patch(state)
                result = callback(state)
                if task_id and self._is_stop_requested(task_id):
                    next_result = dict(result or {})
                    next_result["cancelled"] = True
                    return next_result
                return result

            return guarded_callback

        for field_name in WorkflowCallbacks.__dataclass_fields__:
            guarded[field_name] = wrap(getattr(callbacks, field_name))
        return WorkflowCallbacks(**guarded)

    def _start_background(self, task_id: str, target, *args: Any) -> None:
        try:
            parent_request_id = request_id_var.get()
        except LookupError:
            parent_request_id = None
        target_name = getattr(target, "__name__", target.__class__.__name__)

        def runner() -> None:
            thread_name = threading.current_thread().name
            with RequestContext(request_id=parent_request_id, task_id=task_id):
                log_performance(
                    logger,
                    "background_task_start",
                    request_id=parent_request_id,
                    task_id=task_id,
                    target=target_name,
                    thread_name=thread_name,
                )
                try:
                    with performance_span(
                        logger,
                        "background_task_end",
                        request_id=parent_request_id,
                        task_id=task_id,
                        target=target_name,
                        thread_name=thread_name,
                    ):
                        target(*args)
                except Exception as exc:
                    log_performance(
                        logger,
                        "background_task_failed",
                        level=40,
                        request_id=parent_request_id,
                        task_id=task_id,
                        target=target_name,
                        error_type=type(exc).__name__,
                    )
                    # 尝试标记任务为失败，防止永久卡在运行状态
                    try:
                        self._mark_failed_unless_stable(task_id, f"后台任务异常：{exc}")
                    except Exception:
                        logger.exception("后台任务异常且 set_failed 也失败，task_id=%s", task_id)
                finally:
                    # 兜底清理，防止 _active_runs 泄漏
                    self._leave_active_run(task_id)

        t = threading.Thread(
            target=runner,
            name=f"task-worker-{task_id}",
            daemon=True,
        )
        with self._run_lock:
            self._active_threads[task_id] = t
        t.start()

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
