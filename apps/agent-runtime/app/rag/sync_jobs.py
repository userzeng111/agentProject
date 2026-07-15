"""RAG 同步计划与后台作业。

索引文件仍由 ``EmbeddingProjectNovelCorpusBuilder`` 以暂存文件 + 回滚方式发布。
本模块只负责把耗时操作移出 HTTP 请求，并把计划、确认令牌和作业状态落盘，
因此 API 进程重启后仍能说明上一次作业的结果。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import secrets
import threading
from typing import Any
from uuid import uuid4

from app.observability import get_logger
from app.rag.rebuild_service import FullRebuildRequired, NovelCorpusRebuildService


logger = get_logger(__name__)


class RagSyncBusyError(RuntimeError):
    """已有进程正在执行 RAG 同步。"""


class RagSyncPlanNotFoundError(ValueError):
    """计划不存在、过期或与请求模式不一致。"""


class RagSyncConfirmationError(ValueError):
    """全量构建的二次确认令牌无效。"""


class RagSyncJobService:
    """单 worker 的 RAG 同步任务调度器。

    ``flock`` 在不同 Uvicorn worker/重载进程之间互斥；进程内锁保护计划与
    幂等映射。索引构建过程中持有锁，但 HTTP 请求只负责创建记录并立即返回。
    """

    _CONFIRMATION_TTL = timedelta(minutes=10)
    _POLL_AFTER_MS = 1_000
    _ACTIVE_STATUSES = {"queued", "running"}

    def __init__(self, rebuild_service: NovelCorpusRebuildService) -> None:
        self.rebuild_service = rebuild_service
        self.config = rebuild_service.config
        self._mutex = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-sync")
        self._ensure_storage()
        self._mark_interrupted_job()

    @property
    def _root(self) -> Path:
        return self.config.library_dir / "sync_jobs"

    @property
    def _plans_root(self) -> Path:
        return self._root / "plans"

    @property
    def _jobs_root(self) -> Path:
        return self._root / "jobs"

    @property
    def _current_path(self) -> Path:
        return self._root / "current.json"

    @property
    def _lock_path(self) -> Path:
        return self._root / "worker.lock"

    def close(self) -> None:
        """停止接收新作业；正在运行的作业由进程退出时中断并在下次启动标记。"""
        self._executor.shutdown(wait=False, cancel_futures=False)

    def create_plan(self, mode: str) -> dict[str, Any]:
        self._validate_mode(mode)
        try:
            summary = self.rebuild_service.plan_sync(mode)
        except FullRebuildRequired as exc:
            return {
                "plan_id": "",
                "mode": mode,
                "state": "full_rebuild_required",
                "can_start": False,
                "reason_code": exc.reason_code,
                "reason": exc.reason,
                "summary": None,
                "confirmation": {"required": False},
            }

        now = self._now()
        plan_id = uuid4().hex
        confirmation: dict[str, Any] = {"required": mode == "full"}
        plan_record: dict[str, Any] = {
            "plan_id": plan_id,
            "mode": mode,
            "state": "ready",
            "can_start": True,
            "created_at": now.isoformat(),
            "expires_at": (now + self._CONFIRMATION_TTL).isoformat(),
            "summary": summary,
            "confirmation_required": mode == "full",
        }
        if mode == "full":
            token = secrets.token_urlsafe(32)
            plan_record["confirmation_token_hash"] = self._token_hash(token)
            confirmation["token"] = token
            confirmation["expires_at"] = plan_record["expires_at"]

        with self._mutex:
            self._write_json(self._plan_path(plan_id), plan_record)

        return {
            "plan_id": plan_id,
            "mode": mode,
            "state": "ready",
            "can_start": True,
            "summary": summary,
            "confirmation": confirmation,
        }

    def create_job(
        self,
        *,
        plan_id: str,
        mode: str,
        idempotency_key: str,
        confirmation_token: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """创建任务并返回 ``(job, created)``，永不在请求线程中执行嵌入。"""
        self._validate_mode(mode)
        request_key = idempotency_key.strip()
        if not request_key:
            raise ValueError("idempotency_key 不能为空。")
        with self._mutex:
            existing = self._find_job_by_idempotency_key(request_key)
            if existing is not None:
                return existing, False

            plan = self._load_json(self._plan_path(plan_id))
            if plan is None or str(plan.get("mode")) != mode:
                raise RagSyncPlanNotFoundError("同步计划不存在或与请求模式不一致，请重新预检。")
            if self._is_expired(plan):
                raise RagSyncPlanNotFoundError("同步计划已过期，请重新预检后再执行。")
            if plan.get("state") != "ready":
                raise RagSyncPlanNotFoundError("同步计划不可执行，请重新预检。")
            if bool(plan.get("confirmation_required")):
                self._validate_confirmation(plan, confirmation_token)

            lock_handle = self._try_acquire_file_lock()
            if lock_handle is None:
                raise RagSyncBusyError("已有 RAG 同步任务正在运行，请等待其完成。")

            job_id = uuid4().hex
            now = self._now().isoformat()
            job = {
                "job_id": job_id,
                "plan_id": plan_id,
                "mode": mode,
                "status": "queued",
                "phase": "queued",
                "phase_label": "等待后台工作线程启动",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
                "idempotency_key": request_key,
                "poll_after_ms": self._POLL_AFTER_MS,
            }
            try:
                self._write_job(job)
                self._write_json(self._current_path, job)
                # 成功接收后立即作废全量令牌，避免同一令牌被重放创建第二个作业。
                plan["state"] = "started"
                plan["started_at"] = now
                self._write_json(self._plan_path(plan_id), plan)
                self._executor.submit(self._run_job, job_id, lock_handle)
            except Exception:
                lock_handle.close()
                raise
        return self._public_job(job), True

    def get_current_job(self) -> dict[str, Any] | None:
        with self._mutex:
            current = self._load_json(self._current_path)
            if current is None:
                return None
            job_id = str(current.get("job_id") or "")
            job = self._load_job(job_id) if job_id else None
            return self._public_job(job or current)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._mutex:
            return self._public_job(self._load_job(job_id))

    def _run_job(self, job_id: str, lock_handle) -> None:
        try:
            self._update_job(
                job_id,
                status="running",
                phase="collect_sources",
                phase_label="扫描语料来源",
                progress=5,
                started_at=self._now().isoformat(),
            )

            def report_phase(phase: str, label: str, progress: int) -> None:
                self._update_job(
                    job_id,
                    status="running",
                    phase=phase,
                    phase_label=label,
                    progress=progress,
                )

            job = self._load_job(job_id)
            if job is None:
                return
            result = self.rebuild_service.synchronize(
                str(job["mode"]), phase_callback=report_phase
            )
            self._update_job(
                job_id,
                status="succeeded",
                phase="completed",
                phase_label="同步完成",
                progress=100,
                result=result,
                finished_at=self._now().isoformat(),
            )
        except FullRebuildRequired as exc:
            # 理论上计划已拦截；若来源/索引在排队后发生变化，也绝不转全量。
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                phase_label="需要全量重建",
                progress=100,
                error={"code": exc.reason_code, "message": exc.reason},
                finished_at=self._now().isoformat(),
            )
        except Exception as exc:  # 失败时 builder 的暂存/回滚保证旧索引继续可读。
            logger.exception("RAG 同步后台作业失败 job_id=%s", job_id)
            self._update_job(
                job_id,
                status="failed",
                phase="failed",
                phase_label="同步失败",
                progress=100,
                error={"code": "sync_failed", "message": str(exc) or type(exc).__name__},
                finished_at=self._now().isoformat(),
            )
        finally:
            try:
                lock_handle.close()
            except Exception:
                logger.warning("关闭 RAG 同步文件锁失败 job_id=%s", job_id, exc_info=True)

    def _update_job(self, job_id: str, **changes: Any) -> None:
        with self._mutex:
            job = self._load_job(job_id)
            if job is None:
                return
            job.update(changes)
            job["updated_at"] = self._now().isoformat()
            self._write_job(job)
            self._write_json(self._current_path, job)

    def _mark_interrupted_job(self) -> None:
        with self._mutex:
            current = self._load_json(self._current_path)
            if current is None or current.get("status") not in self._ACTIVE_STATUSES:
                return
            job_id = str(current.get("job_id") or "")
            job = self._load_job(job_id) or current
            job.update(
                {
                    "status": "interrupted",
                    "phase": "interrupted",
                    "phase_label": "服务重启导致任务中断",
                    "progress": 100,
                    "error": {
                        "code": "service_restarted",
                        "message": "服务重启导致同步任务中断，请重新预检后发起同步。",
                    },
                    "finished_at": self._now().isoformat(),
                    "updated_at": self._now().isoformat(),
                }
            )
            self._write_job(job)
            self._write_json(self._current_path, job)

    def _find_job_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        for path in self._jobs_root.glob("*.json"):
            job = self._load_json(path)
            if job is not None and job.get("idempotency_key") == idempotency_key:
                return self._public_job(job)
        return None

    def _validate_confirmation(self, plan: dict[str, Any], token: str | None) -> None:
        expected = str(plan.get("confirmation_token_hash") or "")
        actual = self._token_hash(token or "")
        if not expected or not token or not secrets.compare_digest(expected, actual):
            raise RagSyncConfirmationError("全量重建需要有效的二次确认令牌，请重新预检。")

    def _try_acquire_file_lock(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        except OSError:
            handle.close()
            raise
        return handle

    def _ensure_storage(self) -> None:
        self._plans_root.mkdir(parents=True, exist_ok=True)
        self._jobs_root.mkdir(parents=True, exist_ok=True)

    def _plan_path(self, plan_id: str) -> Path:
        self._validate_identifier(plan_id, "plan_id")
        return self._plans_root / f"{plan_id}.json"

    def _job_path(self, job_id: str) -> Path:
        self._validate_identifier(job_id, "job_id")
        return self._jobs_root / f"{job_id}.json"

    def _load_job(self, job_id: str) -> dict[str, Any] | None:
        if not job_id:
            return None
        try:
            return self._load_json(self._job_path(job_id))
        except ValueError:
            return None

    def _write_job(self, job: dict[str, Any]) -> None:
        self._write_json(self._job_path(str(job["job_id"])), job)

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            logger.warning("读取 RAG 同步状态文件失败 path=%s", path, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)

    def _public_job(self, job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        # 幂等键只用于服务端去重，不能回显给浏览器。
        return {key: value for key, value in job.items() if key != "idempotency_key"}

    def _is_expired(self, plan: dict[str, Any]) -> bool:
        try:
            expires_at = datetime.fromisoformat(str(plan["expires_at"]))
        except (KeyError, TypeError, ValueError):
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= self._now()

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in {"incremental", "full"}:
            raise ValueError("RAG 同步模式必须是 incremental 或 full。")

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not value or len(value) > 128 or not value.replace("-", "").isalnum():
            raise ValueError(f"{label} 格式不正确。")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
