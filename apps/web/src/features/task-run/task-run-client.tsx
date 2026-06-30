"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Alert,
  Avatar,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Container,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  CircularProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  Close as CloseIcon,
  Psychology as ThinkIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
  Delete as DeleteIcon,
  Cancel as CancelIcon,
} from "@mui/icons-material";
import { cancelTask, continueTask, deleteTask, getApiBase, getCurrentChapters, getModelCatalog, getWorkspace, normalizeModelOptions, recoverTask, runTask } from "@/lib/api";
import RecoveryDialog from "@/features/task-recovery/recovery-dialog";
import {
  derivePrimaryRecoveryAction,
  filterRecoveryModels,
  resolveRecoveryPreview,
} from "@/features/task-recovery/recovery-state.mjs";
import { formatModelRefreshStatus, resolveSelectionAfterRefresh } from "@/features/task-models/model-refresh-state.mjs";
import {
  buildChapterProgress,
  buildThinkingGroups,
  resolveEventStreamErrorTransition,
  resolveTerminalEventStreamState,
} from "@/features/task-run/task-run-state.mjs";
import DebugPanel from "@/features/task-run/debug-panel";
import WorkflowOverviewCard from "@/features/task-run/workflow-overview-card";
import { selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { resultHref, reviewHref } from "@/lib/task-routes";
import { getValidationLinkFromError } from "@/features/chat/model-validation-state.mjs";
import {
  ContextStatus,
  ModelCapabilities,
  ModelOption,
  ModelRefreshState,
  RecoverTaskPayload,
  RecoveryMode,
  ResponseCacheStatus,
  SupervisorSubtaskItem,
  SupervisorSubtaskStatus,
  TaskStatus,
  WorkspaceEvent,
  WorkspaceResponse,
} from "@/lib/types";

const statusMap: Record<TaskStatus, { label: string; color: "default" | "success" | "warning" | "error" }> = {
  created: { label: "待启动", color: "default" },
  sources_ingested: { label: "素材已入库", color: "default" },
  planning: { label: "规划中", color: "warning" },
  waiting_outline_review: { label: "待大纲审核", color: "warning" },
  ready_for_batch: { label: "可继续创作", color: "success" },
  drafting: { label: "正文生成中", color: "warning" },
  waiting_manual_action: { label: "待人工处理", color: "warning" },
  assembling: { label: "结果整理中", color: "warning" },
  completed: { label: "已完成", color: "success" },
  cancelled: { label: "已取消", color: "error" },
  failed: { label: "失败", color: "error" },
  waiting_chapter_review: { label: "待章节审核", color: "warning" },
  waiting_verification_review: { label: "待验证审核", color: "warning" },
};

const supervisorStatusMap: Record<
  SupervisorSubtaskStatus,
  { label: string; color: "default" | "success" | "warning" | "error" | "info" }
> = {
  pending: { label: "待规划", color: "default" },
  ready: { label: "就绪", color: "info" },
  running: { label: "执行中", color: "warning" },
  blocked: { label: "阻塞", color: "default" },
  completed: { label: "已完成", color: "success" },
  failed: { label: "失败", color: "error" },
};

function getDeletePrompt(status: TaskStatus): string {
  switch (status) {
    case "waiting_chapter_review":
    case "waiting_verification_review":
      return "该任务已有章节生成，删除后将丢失所有已生成内容。确认删除？";
    case "waiting_outline_review":
      return "该任务大纲已生成，删除后将丢失大纲内容。确认删除？";
    case "created":
    case "sources_ingested":
      return "该任务尚未开始编写，确认删除？";
    case "failed":
      return "该任务执行失败，确认删除？";
    case "cancelled":
      return "该任务已取消，删除后将丢失所有已生成内容且不可恢复。确认删除？";
    case "ready_for_batch":
      return "该任务已有部分进度，删除后将丢失已生成内容。确认删除？";
    default:
      return "确认删除该任务？此操作不可恢复。";
  }
}

const streamPathCandidates = (taskId: string) => [
  `/api/tasks/${taskId}/events/stream`,
  `/api/tasks/${taskId}/workspace/stream`,
  `/api/tasks/${taskId}/workspace/events`,
  `/api/tasks/${taskId}/sse`,
];

function formatEventRef(event: WorkspaceEvent) {
  const refs = [event.md_ref, event.json_ref].filter(Boolean);
  return refs.length ? `引用：${refs.join(" · ")}` : "";
}

function formatEventTime(value: string) {
  return new Date(value).toLocaleString();
}

function formatActionKindLabel(kind?: string) {
  const labels: Record<string, string> = {
    run: "启动执行",
    resume: "审核继续",
    continue: "继续创作",
    recover: "恢复重试",
  };
  return labels[kind || ""] || kind || "";
}

function resolveWorkspaceTaskModelId(workspace?: WorkspaceResponse | null) {
  return (
    workspace?.request_preview?.creative_model_id ||
    workspace?.meta.creative_model_id ||
    workspace?.request_preview?.default_model_id ||
    workspace?.meta.default_model_id ||
    workspace?.request_preview?.model_id ||
    workspace?.meta.model_id ||
    ""
  );
}

function formatWorkspaceReviewModel(workspace?: WorkspaceResponse | null) {
  const mode = workspace?.request_preview?.auto_review_model_mode || workspace?.meta.auto_review_model_mode;
  const reviewModelId = workspace?.request_preview?.review_model_id || workspace?.meta.review_model_id || "";
  const creativeModelId = resolveWorkspaceTaskModelId(workspace);
  if (mode === "follow_creative") {
    return `跟随创作模型${creativeModelId ? `（${creativeModelId}）` : ""}`;
  }
  return reviewModelId || "未设置";
}

function formatTokenCount(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "未上报";
  }
  return value.toLocaleString();
}

function formatPercent(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未上报";
  }
  return `${Math.round(value * 100)}%`;
}

function hasPayload<T extends object>(value?: T | null): value is T {
  return Boolean(value) && Object.keys(value ?? {}).length > 0;
}

function resolveContextStatus(workspace: WorkspaceResponse): ContextStatus | undefined {
  return hasPayload(workspace.context_status) ? workspace.context_status : undefined;
}

function resolveResponseCacheStatus(workspace: WorkspaceResponse): ResponseCacheStatus | undefined {
  return hasPayload(workspace.response_cache_status) ? workspace.response_cache_status : undefined;
}

function resolveModelCapabilities(workspace: WorkspaceResponse): ModelCapabilities | undefined {
  return workspace.request_preview?.model_capabilities || workspace.meta.model_capabilities;
}

function resolveRecoveryReason(workspace: WorkspaceResponse) {
  if (typeof workspace.blocked_reason === "string" && workspace.blocked_reason) {
    return workspace.blocked_reason;
  }
  const event = [...(workspace.recent_events || [])]
    .reverse()
    .find((item) => item.event_type === "task.recovery.blocked" && typeof item.payload?.reason === "string");
  return event?.payload?.reason || "";
}

function formatRecoveryReason(reason: string) {
  if (!reason) {
    return "";
  }
  const labels: Record<string, string> = {
    missing_stable_state: "缺少可恢复的稳定产物",
    draft_batch_generation_failed: "章节生成失败，可恢复后切换模型重试",
  };
  return labels[reason] || reason;
}

function formatRecoveryActionLabel(action?: string) {
  const labels: Record<string, string> = {
    recover_to_stable: "回填最近稳定阶段",
    restart_from_input: "按原始输入重新开始",
  };
  return labels[action || ""] || action || "未提供";
}

function getRecoveryOptions(workspace?: WorkspaceResponse | null) {
  return Array.isArray(workspace?.recovery_options) ? workspace.recovery_options : [];
}

function resolveInitialRecoveryAction(workspace?: WorkspaceResponse | null): RecoveryMode | null {
  const primaryAction = derivePrimaryRecoveryAction(workspace);
  if (primaryAction?.action) {
    return primaryAction.action;
  }

  if (workspace?.recommended_action === "recover_to_stable" || workspace?.recommended_action === "restart_from_input") {
    return workspace.recommended_action;
  }

  const availableOption = getRecoveryOptions(workspace).find((option) => option.available);
  return availableOption?.action ?? null;
}

function formatContextWindowLabel(capabilities?: ModelCapabilities) {
  const contextWindow = capabilities?.context_window;
  if (!contextWindow) {
    return "上下文窗口：未上报";
  }
  return `上下文窗口：${formatTokenCount(contextWindow.max_input_tokens || contextWindow.max_total_tokens)} tokens`;
}

function formatContextCacheLabel(capabilities?: ModelCapabilities, contextStatus?: ContextStatus) {
  if (contextStatus?.cache_hit === true) {
    return "上下文缓存：本轮已命中";
  }
  if (contextStatus?.cache_hit === false) {
    return "上下文缓存：本轮未命中";
  }
  if (capabilities?.cache?.runtime_context_cache) {
    return "上下文缓存：支持运行时上下文缓存";
  }
  if (capabilities?.cache) {
    return "上下文缓存：未上报";
  }
  return "上下文缓存：未声明";
}

function formatResponseCacheLabel(capabilities?: ModelCapabilities, responseCacheStatus?: ResponseCacheStatus) {
  if (responseCacheStatus?.cache_hit === true) {
    return "响应缓存：本轮已命中";
  }
  if (responseCacheStatus?.cache_hit === false) {
    return "响应缓存：本轮未命中";
  }
  if (capabilities?.cache?.runtime_response_cache || capabilities?.cache?.response_cache) {
    return "响应缓存：支持运行时响应缓存";
  }
  if (capabilities?.cache) {
    return "响应缓存：未上报";
  }
  return "响应缓存：未声明";
}

function formatCompressionLabel(capabilities?: ModelCapabilities, contextStatus?: ContextStatus) {
  if (contextStatus?.compression_applied === true) {
    return `压缩：已启用${contextStatus.compression_ratio ? `（压缩率 ${formatPercent(contextStatus.compression_ratio)}）` : ""}`;
  }
  if (contextStatus?.compression_applied === false) {
    return "压缩：本轮未触发";
  }
  if (capabilities?.compression?.supported) {
    return `压缩：支持${capabilities.compression.strategy ? ` ${capabilities.compression.strategy}` : ""}`.trim();
  }
  if (capabilities?.compression?.may_compress) {
    return "压缩：可能按需启用";
  }
  return "压缩：未声明";
}

function buildSummaryStream(events: WorkspaceEvent[], activeTraceSummary?: string) {
  const traceEvents = events.filter(
    (event) => event.event_type === "trace.summary" || typeof event.payload?.summary === "string",
  );

  if (traceEvents.length) {
    return traceEvents.map((event) => ({
      id: event.event_id,
      title: String(event.payload?.title || event.payload?.summary || event.message || "过程摘要已更新"),
      subtitle: [event.payload?.detail, `${event.stage} · ${formatEventTime(event.created_at)}`]
        .filter(Boolean)
        .join(" · "),
    }));
  }

  const fallback = events
    .filter((event) => !event.event_type.startsWith("chapter."))
    .slice(-8)
    .map((event) => ({
      id: event.event_id,
      title: event.message,
      subtitle: `${event.stage} · ${formatEventTime(event.created_at)}`,
    }));

  if (!fallback.length && activeTraceSummary) {
    return [
      {
        id: "active-trace-summary",
        title: activeTraceSummary,
        subtitle: "当前过程摘要",
      },
    ];
  }

  return fallback;
}

function countIncomingDependencies(workspace: WorkspaceResponse, subtaskId: string) {
  return workspace.supervisor_plan?.dependencies.filter((edge) => edge.downstream_subtask_id === subtaskId).length ?? 0;
}

function countOutgoingDependencies(workspace: WorkspaceResponse, subtaskId: string) {
  return workspace.supervisor_plan?.dependencies.filter((edge) => edge.upstream_subtask_id === subtaskId).length ?? 0;
}

function resolveSupervisorStatus(subtask: SupervisorSubtaskItem) {
  return supervisorStatusMap[subtask.status] ?? supervisorStatusMap.pending;
}

function buildSystemStages(events: WorkspaceEvent[]) {
  return events.filter((event) => !event.event_type.startsWith("chapter.") && event.event_type !== "model.thinking").slice(-10);
}

function ValidationErrorAlert({ message, modelId }: { message: string; modelId: string }) {
  const href = getValidationLinkFromError(message, modelId);
  return (
    <Alert
      severity="error"
      action={
        href ? (
          <Button component={Link} href={href} color="inherit" size="small">
            去 AI 对话验证
          </Button>
        ) : undefined
      }
    >
      {message}
    </Alert>
  );
}

export default function TaskRunClient({ taskId }: { taskId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const resolvedTaskId = taskId || searchParams.get("id") || "";
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [streamState, setStreamState] = useState("未连接事件流");
  const [activeTab, setActiveTab] = useState(0);
  const [chapterDialogOpen, setChapterDialogOpen] = useState(false);
  const [selectedChapter, setSelectedChapter] = useState<{ number: number; title: string; summary: string; content: string } | null>(null);
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const [seenThinkingKeys, setSeenThinkingKeys] = useState<Set<string>>(new Set());
  const [requestedChapterCount, setRequestedChapterCount] = useState(3);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({ loading: false, error: "" });
  const [actionModelId, setActionModelId] = useState("");
  const [recoveryDialogOpen, setRecoveryDialogOpen] = useState(false);
  const [selectedRecoveryAction, setSelectedRecoveryAction] = useState<RecoveryMode>("recover_to_stable");
  const [recoveryModelId, setRecoveryModelId] = useState("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMsg, setSnackbarMsg] = useState("");
  const [summaryExpanded, setSummaryExpanded] = useState(true);
  const [logTabExpanded, setLogTabExpanded] = useState(true);
  const [tab1Expanded, setTab1Expanded] = useState(true);
  const [tab2Expanded, setTab2Expanded] = useState(true);
  const [tab3Expanded, setTab3Expanded] = useState(true);
  const [tab4Expanded, setTab4Expanded] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);
  const continueRequestIdRef = useRef<string | null>(null);
  const currentActionModelIdRef = useRef("");
  const currentTaskModelIdRef = useRef("");
  const currentModelOptionsRef = useRef<ModelOption[]>([]);

  // 提前计算 thinkingGroups，确保相关 hook 位于条件 return 之前，避免 Hook 数量不一致
  const thinkingGroups = useMemo(() => {
    if (!workspace) return [];
    return buildThinkingGroups(workspace.recent_events, workspace.meta.status, {
      minimumChapterNumber: workspace.novel_progress?.next_chapter_number,
    });
  }, [workspace]);

  // 自动展开新到达的活跃思考组（用户未手动折叠过的）
  useEffect(() => {
    if (thinkingGroups.length === 0) return;
    setExpandedThinking((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const group of thinkingGroups) {
        const key = group.unitId;
        if (!seenThinkingKeys.has(key)) {
          if (!(key in next)) {
            next[key] = group.isActive;
            changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
    setSeenThinkingKeys((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const group of thinkingGroups) {
        if (!next.has(group.unitId)) {
          next.add(group.unitId);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [thinkingGroups, seenThinkingKeys]);

  const refreshWorkspace = useCallback(async () => {
    if (!resolvedTaskId) {
      setError("缺少任务 ID");
      setWorkspace(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const nextWorkspace = await getWorkspace(resolvedTaskId);
      setWorkspace(nextWorkspace);
      setError("");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "读取工作台失败");
    } finally {
      setLoading(false);
    }
  }, [resolvedTaskId]);

  useEffect(() => {
    void refreshWorkspace();
  }, [refreshWorkspace]);

  const showSnackbar = useCallback((msg: string) => {
    setSnackbarMsg(msg);
    setSnackbarOpen(true);
  }, []);

  const handleCancelTask = useCallback(async () => {
    if (!resolvedTaskId) return;
    if (!window.confirm("确认取消该任务？取消后任务将停止运行。")) return;
    try {
      await cancelTask(resolvedTaskId);
      showSnackbar("任务已取消");
      void refreshWorkspace();
    } catch (err) {
      showSnackbar(err instanceof Error ? err.message : "取消任务失败");
    }
  }, [resolvedTaskId, showSnackbar, refreshWorkspace]);

  const handleDeleteTask = useCallback(async () => {
    if (!resolvedTaskId || !workspace) return;
    const prompt = getDeletePrompt(workspace.meta.status);
    if (!window.confirm(prompt)) return;
    try {
      await deleteTask(resolvedTaskId);
      showSnackbar("任务已删除");
      router.push("/");
    } catch (err) {
      showSnackbar(err instanceof Error ? err.message : "删除任务失败");
    }
  }, [resolvedTaskId, workspace, showSnackbar, router]);

  useEffect(() => {
    const nextDefault = workspace?.novel_progress?.default_batch_size;
    if (typeof nextDefault === "number" && Number.isFinite(nextDefault) && nextDefault > 0) {
      setRequestedChapterCount(nextDefault);
    }
  }, [workspace?.novel_progress?.default_batch_size]);

  const currentTaskModelId = resolveWorkspaceTaskModelId(workspace);

  useEffect(() => {
    currentActionModelIdRef.current = actionModelId;
  }, [actionModelId]);

  useEffect(() => {
    currentTaskModelIdRef.current = currentTaskModelId;
  }, [currentTaskModelId]);

  useEffect(() => {
    currentModelOptionsRef.current = models;
  }, [models]);

  const loadModels = useCallback(async (refresh = false) => {
    try {
      setModelRefresh((current) => ({ ...current, loading: true, error: "" }));
      const catalog = await getModelCatalog({ refresh });
      const nextModels = normalizeModelOptions(catalog.data ?? []);
      const nextSelectableModels = selectNovelTaskModels(nextModels);
      const currentEffectiveModelId = currentActionModelIdRef.current || currentTaskModelIdRef.current;
      const nextSelection = resolveSelectionAfterRefresh({
        currentModelId: currentEffectiveModelId,
        availableModels: nextSelectableModels,
      });
      setModels(nextModels);
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: "",
        attemptedRefresh: current.attemptedRefresh || refresh,
        fetchedAt: catalog.meta?.fetched_at,
        cacheAgeSeconds: catalog.meta?.cache_age_seconds,
        cacheTtlSeconds: catalog.meta?.cache_ttl_seconds,
        cached: catalog.meta?.cached,
        invalidated: refresh && nextSelection.invalidated,
        invalidatedModelLabel:
          refresh && nextSelection.invalidated
            ? currentModelOptionsRef.current.find((option) => option.id === currentEffectiveModelId)?.display_name ||
              currentEffectiveModelId ||
              undefined
            : undefined,
      }));
    } catch (loadError) {
      setModels([]);
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: loadError instanceof Error ? loadError.message : "读取模型列表失败",
        attemptedRefresh: current.attemptedRefresh || refresh,
      }));
    }
  }, []);

  useEffect(() => {
    void loadModels(false);
  }, [loadModels]);

  useEffect(() => {
    setModelRefresh({ loading: false, error: "" });
    setRecoveryDialogOpen(false);
    setSelectedRecoveryAction("recover_to_stable");
    setRecoveryModelId("");
  }, [resolvedTaskId]);

  const selectableModels: ModelOption[] = selectNovelTaskModels(models);
  const resolvedActionModelId = selectableModels.some((item) => item.id === actionModelId)
    ? actionModelId
    : "";
  const validationErrorModelId = resolvedActionModelId || actionModelId || currentTaskModelId;
  const recoveryPreview = resolveRecoveryPreview(workspace, selectedRecoveryAction);
  const recoverySelectableModels = filterRecoveryModels(selectableModels, recoveryPreview?.allowed_model_ids);
  const defaultRecoveryModelId =
    recoveryPreview?.default_model_id ||
    currentTaskModelId ||
    "";

  useEffect(() => {
    if (actionModelId && selectableModels.some((item) => item.id === actionModelId)) {
      return;
    }
    const savedModelId = localStorage.getItem("novel-agent:action-model-id");
    if (savedModelId && selectableModels.some((item) => item.id === savedModelId)) {
      setActionModelId(savedModelId);
      return;
    }
    if (currentTaskModelId && selectableModels.some((item) => item.id === currentTaskModelId)) {
      setActionModelId(currentTaskModelId);
      return;
    }
    setActionModelId("");
  }, [actionModelId, currentTaskModelId, selectableModels]);

  const hasValidActionModel = Boolean(resolvedActionModelId);

  function handleActionModelChange(nextModelId: string) {
    setActionModelId(nextModelId);
    if (nextModelId) {
      localStorage.setItem("novel-agent:action-model-id", nextModelId);
    } else {
      localStorage.removeItem("novel-agent:action-model-id");
    }
    setModelRefresh((current) => ({ ...current, invalidated: false, invalidatedModelLabel: undefined }));
  }

  useEffect(() => {
    if (!recoveryDialogOpen) {
      return;
    }
    if (recoveryModelId && recoverySelectableModels.some((item) => item.id === recoveryModelId)) {
      return;
    }
    if (defaultRecoveryModelId && recoverySelectableModels.some((item) => item.id === defaultRecoveryModelId)) {
      setRecoveryModelId(defaultRecoveryModelId);
      return;
    }
    setRecoveryModelId("");
  }, [defaultRecoveryModelId, recoveryDialogOpen, recoveryModelId, recoverySelectableModels]);

  useEffect(() => {
    if (!resolvedTaskId) {
      setStreamState("缺少任务 ID，无法连接事件流");
      return;
    }
    const initialTerminalState = resolveTerminalEventStreamState(workspace?.meta?.status || "");
    if (initialTerminalState) {
      setStreamState(initialTerminalState);
      return;
    }

    let disposed = false;
    let source: EventSource | null = null;
    let refreshTimeout: ReturnType<typeof setTimeout> | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    const candidatePaths = streamPathCandidates(resolvedTaskId);
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 3;
    const RECONNECT_DELAY = 2000;
    let terminalEventReceived = false;
    let terminalStreamState = "";

    const tryConnect = (index: number) => {
      if (disposed || index >= candidatePaths.length) {
        if (!disposed) {
          setStreamState("事件流未就绪，当前使用手动刷新");
        }
        return;
      }

      const target = `${getApiBase()}${candidatePaths[index]}`;
      setStreamState(`正在连接 ${candidatePaths[index]}`);
      source = new EventSource(target);
      eventSourceRef.current = source;

      let opened = false;

      source.onopen = () => {
        opened = true;
        reconnectAttempts = 0;
        setStreamState("事件流已连接");
      };

      const handleRefresh = () => {
        if (refreshTimeout) return;
        refreshTimeout = setTimeout(() => {
          refreshTimeout = null;
        }, 3000);
        void refreshWorkspace();
      };
      source.addEventListener("snapshot", handleRefresh);
      source.addEventListener("task.event", handleRefresh);
      source.addEventListener("task.done", (event) => {
        terminalEventReceived = true;
        try {
          const payload = JSON.parse((event as MessageEvent).data || "{}");
          terminalStreamState = resolveTerminalEventStreamState(payload?.event_type || "");
        } catch {
          terminalStreamState = "";
        }
        if (!terminalStreamState) {
          terminalStreamState = "任务已结束，事件流已关闭";
        }
        setStreamState(terminalStreamState);
        handleRefresh();
      });

      source.onerror = () => {
        source?.close();
        if (disposed) {
          return;
        }
        const transition = resolveEventStreamErrorTransition({
          opened,
          terminalEventReceived,
          reconnectAttempts,
          maxReconnect: MAX_RECONNECT,
          reconnectDelaySeconds: RECONNECT_DELAY / 1000,
          terminalState: terminalStreamState,
        });
        if (transition.action === "terminal") {
          setStreamState(transition.streamState);
          return;
        }
        if (transition.action === "next_path") {
          tryConnect(index + 1);
          return;
        }
        reconnectAttempts = transition.nextReconnectAttempts;
        setStreamState(transition.streamState);
        if (transition.action === "reconnect") {
          reconnectTimeout = setTimeout(() => {
            reconnectTimeout = null;
            if (!disposed) {
              tryConnect(0);
            }
          }, RECONNECT_DELAY);
          return;
        }
      };
    };

    tryConnect(0);

    return () => {
      disposed = true;
      if (refreshTimeout) clearTimeout(refreshTimeout);
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      source?.close();
      eventSourceRef.current = null;
    };
  }, [resolvedTaskId, refreshWorkspace, workspace?.meta?.status]);

  // 全局前端错误捕获：窗口级错误与未处理 Promise 拒绝
  useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      const msg = `[前端错误] ${event.message} @ ${event.filename}:${event.lineno}`;
      console.error(msg, event.error);
      setSnackbarMsg(msg);
      setSnackbarOpen(true);
    };
    const handleRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason instanceof Error ? event.reason.message : String(event.reason);
      const msg = `[前端未处理Promise] ${reason}`;
      console.error(msg, event.reason);
      setSnackbarMsg(msg);
      setSnackbarOpen(true);
    };
    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  async function handleRun() {
    if (!hasValidActionModel) {
      setError("任务默认模型当前不可用，请先手动选择本次动作模型。");
      return;
    }
    try {
      setRunning(true);
      await runTask(resolvedTaskId, { model_id: resolvedActionModelId || undefined });
      await refreshWorkspace();
      setError("");
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "运行失败");
    } finally {
      setRunning(false);
    }
  }

  function handleOpenRecoveryDialog() {
    const nextAction = resolveInitialRecoveryAction(workspace);
    if (!nextAction) {
      return;
    }
    setSelectedRecoveryAction(nextAction);
    setRecoveryModelId("");
    setRecoveryDialogOpen(true);
  }

  async function handleRecover(payload: RecoverTaskPayload) {
    try {
      setRunning(true);
      await recoverTask(resolvedTaskId, payload);
      await refreshWorkspace();
      setRecoveryDialogOpen(false);
      setError("");
    } catch (recoverError) {
      setError(recoverError instanceof Error ? recoverError.message : "恢复任务失败");
    } finally {
      setRunning(false);
    }
  }

  async function handleContinueDraft() {
    if (!hasValidActionModel) {
      setError("任务默认模型当前不可用，请先手动选择本次动作模型。");
      return;
    }
    try {
      setRunning(true);
      const requestId = continueRequestIdRef.current ?? (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Math.random().toString(36).substring(2, 10)}-${Math.random().toString(36).substring(2, 6)}-${Math.random().toString(36).substring(2, 6)}-${Math.random().toString(36).substring(2, 6)}-${Math.random().toString(36).substring(2, 10)}${Date.now().toString(36).substring(0, 4)}`);
      continueRequestIdRef.current = requestId;
      await continueTask(resolvedTaskId, {
        requested_chapter_count: requestedChapterCount,
        continue_request_id: requestId,
        model_id: resolvedActionModelId || undefined,
      }, {
        continue_request_id: requestId,
      });
      await refreshWorkspace();
      setError("");
    } catch (continueError) {
      setError(continueError instanceof Error ? continueError.message : "继续创作失败");
    } finally {
      continueRequestIdRef.current = null;
      setRunning(false);
    }
  }

  async function handleChapterClick(chapterNumber: number, chapterTitle: string) {
    try {
      const data = await getCurrentChapters(resolvedTaskId);
      const chapter = data.chapters?.find((ch) => ch.number === chapterNumber);
      if (chapter) {
        setSelectedChapter({
          number: chapter.number,
          title: chapter.title || chapterTitle,
          summary: chapter.summary || "",
          content: chapter.content || "正文内容暂不可用",
        });
      } else {
        setSelectedChapter({
          number: chapterNumber,
          title: chapterTitle,
          summary: "暂无摘要",
          content: "该章节正文尚未写入磁盘，请稍后再试。",
        });
      }
      setChapterDialogOpen(true);
    } catch {
      setSelectedChapter({
        number: chapterNumber,
        title: chapterTitle,
        summary: "",
        content: "读取章节内容失败，请稍后再试。",
      });
      setChapterDialogOpen(true);
    }
  }

  if (loading && !workspace) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }}>
          <Typography>正在读取工作台...</Typography>
        </Box>
      </Container>
    );
  }

  if (!workspace) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2} sx={{ py: 6 }}>
          <ValidationErrorAlert message={error || "读取工作台失败"} modelId={validationErrorModelId} />
          <Box>
            <Button variant="outlined" onClick={() => void refreshWorkspace()}>
              重新加载
            </Button>
          </Box>
        </Stack>
      </Container>
    );
  }

  const status = statusMap[workspace.meta.status] ?? statusMap.created;
  const systemStages = buildSystemStages(workspace.recent_events);
  const chapterProgress = buildChapterProgress(workspace.recent_events, workspace.novel_progress);
  const summaryStream = buildSummaryStream(workspace.recent_events, workspace.active_trace_summary);
  const contextStatus = resolveContextStatus(workspace);
  const responseCacheStatus = resolveResponseCacheStatus(workspace);
  const modelCapabilities = resolveModelCapabilities(workspace);
  const recoveryReason = resolveRecoveryReason(workspace);
  const novelProgress = workspace.novel_progress;
  const primaryRecoveryAction = derivePrimaryRecoveryAction(workspace);
  const primaryRecoveryPreview = primaryRecoveryAction ? resolveRecoveryPreview(workspace, primaryRecoveryAction.action) : null;
  const recoveryStableAvailable = Boolean(
    getRecoveryOptions(workspace).find((option) => option.action === "recover_to_stable")?.available,
  );
  const recommendedRecoveryLabel =
    getRecoveryOptions(workspace).find((option) => option.action === workspace.recommended_action)?.label ||
    formatRecoveryActionLabel(workspace.recommended_action);

  const canReview = [
    "waiting_outline_review",
    "waiting_chapter_review",
    "waiting_verification_review",
  ].includes(workspace.meta.status);

  const isOutlineBatchPhase = workspace.meta.status === "waiting_outline_review" && workspace.outline_phase === "chapter_batches";
  const outlineBatchProgress = isOutlineBatchPhase
    ? `章节计划设计中（已确认 ${workspace.outline_completed_count ?? 0} / ${workspace.outline_total_count ?? 0} 章）`
    : null;
  const debugStreamPath = resolvedTaskId ? streamPathCandidates(resolvedTaskId)[0] : undefined;
  const manualActionValidationHref = getValidationLinkFromError(
    workspace.meta.error_message || "",
    validationErrorModelId,
  );

  return (
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
    <Stack spacing={3} className="page-fade-in">
      {/* 面包屑 + 状态 */}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
        <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
              首页
            </Typography>
          </Link>
          <Typography variant="body2">{workspace.meta.title || taskId}</Typography>
        </Breadcrumbs>
        <Chip color={status.color} label={status.label} />
      </Stack>

      {error ? <ValidationErrorAlert message={error} modelId={validationErrorModelId} /> : null}
      {!error && workspace.state_reconciled ? (
        <Alert severity="info">
          {workspace.reconciliation_summary || "当前页面已自动校正到最新稳定状态。"}
        </Alert>
      ) : null}
      {!error && workspace.meta.status === "waiting_manual_action" && workspace.meta.error_message ? (
        <Alert
          severity="warning"
          action={
            manualActionValidationHref ? (
              <Button component={Link} href={manualActionValidationHref} color="inherit" size="small">
                去 AI 对话验证
              </Button>
            ) : undefined
          }
        >
          <Stack spacing={1}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              当前任务需要人工处理
            </Typography>
            <Typography variant="body2">{workspace.meta.error_message}</Typography>
            {workspace.meta.last_error_detail ? (
              <Typography color="error" variant="body2">
                后台异常详情：{workspace.meta.last_error_detail}
              </Typography>
            ) : null}
            {recoveryReason ? (
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="caption" color="text.secondary">
                  恢复阻塞原因：
                </Typography>
                <Chip label={formatRecoveryReason(recoveryReason)} size="small" variant="outlined" />
              </Stack>
            ) : null}
            <Typography variant="caption" color="text.secondary">
              {primaryRecoveryAction
                ? `可先点击“${primaryRecoveryAction.label}”查看恢复方案；若主恢复动作不可用，再改为按原始输入重新开始。`
                : "当前暂无可执行的恢复方案，请先检查任务状态与模型可用性。"}
            </Typography>
          </Stack>
        </Alert>
      ) : null}

      <WorkflowOverviewCard workspace={workspace} onSelectTab={setActiveTab} />

      {/* 请求摘要卡片 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}>
              <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                请求摘要
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <IconButton
                  size="small"
                  onClick={() => setSummaryExpanded((prev) => !prev)}
                  sx={{ transform: summaryExpanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
                {["created", "sources_ingested"].includes(workspace.meta.status) && (
                  <Button variant="contained" disabled={running || !hasValidActionModel} onClick={handleRun} size="small">
                    {running ? "启动中..." : "开始执行"}
                  </Button>
                )}
                {primaryRecoveryAction && (
                  <Button
                    variant="contained"
                    disabled={running}
                    onClick={handleOpenRecoveryDialog}
                    size="small"
                  >
                    {running ? "提交中..." : primaryRecoveryAction.label}
                  </Button>
                )}
                {workspace.meta.status === "ready_for_batch" && (
                  <Button variant="contained" disabled={running || !hasValidActionModel} onClick={handleContinueDraft} size="small">
                    {running ? "生成中..." : "继续创作"}
                  </Button>
                )}
                {canReview && (
                  <Button component={Link} href={reviewHref(workspace.meta.task_id)} variant="contained" size="small">
                    {isOutlineBatchPhase ? "进入章节计划审核" : "进入审核"}
                  </Button>
                )}
                {isOutlineBatchPhase && outlineBatchProgress && (
                  <Chip label={outlineBatchProgress} size="small" color="info" variant="outlined" />
                )}
                {workspace.meta.status === "completed" && (
                  <Button component={Link} href={resultHref(workspace.meta.task_id)} variant="contained" size="small">
                    查看结果
                  </Button>
                )}
                <Button variant="outlined" onClick={() => void refreshWorkspace()} size="small">
                  刷新
                </Button>
                {["planning", "drafting", "assembling", "waiting_manual_action"].includes(workspace.meta.status) && (
                  <Button
                    variant="outlined"
                    color="warning"
                    size="small"
                    startIcon={<CancelIcon />}
                    onClick={handleCancelTask}
                  >
                    取消任务
                  </Button>
                )}
                {workspace.meta.status === "cancelled" && primaryRecoveryAction && (
                  <Button
                    variant="contained"
                    disabled={running}
                    onClick={handleOpenRecoveryDialog}
                    size="small"
                  >
                    {running ? "提交中..." : "恢复任务"}
                  </Button>
                )}
                {workspace.meta.status === "cancelled" && !primaryRecoveryAction && (
                  <Button
                    variant="outlined"
                    disabled={running}
                    onClick={handleOpenRecoveryDialog}
                    size="small"
                  >
                    查看恢复方案
                  </Button>
                )}
                {workspace.meta.status !== "completed" && !["planning", "drafting", "assembling", "waiting_manual_action", "cancelled"].includes(workspace.meta.status) && (
                  <Button variant="outlined" color="error" size="small" startIcon={<DeleteIcon />} onClick={handleDeleteTask}>
                    删除任务
                  </Button>
                )}
                {workspace.meta.status === "cancelled" && (
                  <Button variant="outlined" color="warning" size="small" startIcon={<DeleteIcon />} onClick={handleDeleteTask}>
                    删除任务
                  </Button>
                )}
              </Stack>
            </Stack>
            <Collapse in={summaryExpanded}>
              <Stack spacing={2}>
            <Typography>{workspace.request_preview?.prompt || workspace.meta.summary || "暂无请求摘要"}</Typography>
            {primaryRecoveryAction ? (
              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  backgroundColor: "rgba(255, 152, 0, 0.06)",
                }}
              >
                <Stack spacing={1}>
                  <Typography variant="subtitle1">恢复方案</Typography>
                  <Typography variant="body2">
                    {recoveryStableAvailable ? "当前存在可回填的稳定阶段。" : "当前没有可回填的稳定阶段。"}
                    推荐动作：{recommendedRecoveryLabel}。
                  </Typography>
                  <Typography variant="body2">当前主 CTA：{primaryRecoveryAction.label}</Typography>
                  {primaryRecoveryPreview ? (
                    <Typography variant="caption" color="text.secondary">
                      当前预览：将定位到 {primaryRecoveryPreview.target_stage_label}
                      {primaryRecoveryPreview.will_resume_generation ? "，并继续进入生成链路。" : "，恢复后停留在该阶段。"}
                    </Typography>
                  ) : (
                    <Typography variant="caption" color="text.secondary">
                      当前动作暂未返回恢复预览。
                    </Typography>
                  )}
                </Stack>
              </Box>
            ) : null}
            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                border: "1px solid",
                borderColor: "divider",
                backgroundColor: "rgba(39, 100, 81, 0.03)",
              }}
            >
              <Stack spacing={1.5}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                  <Typography variant="subtitle1">本次创作动作模型</Typography>
                  <Button size="small" variant="outlined" onClick={() => void loadModels(true)}>
                    刷新模型
                  </Button>
                </Stack>
                <Select
                  size="small"
                  value={hasValidActionModel ? actionModelId : ""}
                  onChange={(event) => handleActionModelChange(event.target.value)}
                  displayEmpty
                  sx={{ maxWidth: 360 }}
                >
                  <MenuItem value="">
                    <em>请选择本次创作动作模型</em>
                  </MenuItem>
                  {selectableModels.length ? (
                    selectableModels.map((model) => (
                      <MenuItem key={model.id} value={model.id}>
                        {(model.display_name || model.id) + (model.provider ? ` · ${model.provider}` : "")}
                      </MenuItem>
                    ))
                  ) : (
                    <MenuItem value="" disabled>
                      暂无可用模型
                    </MenuItem>
                  )}
                </Select>
                {!selectableModels.length ? (
                  <Alert severity="warning">当前没有可用于小说任务流的在线模型，请先刷新模型或检查网关配置。</Alert>
                ) : !hasValidActionModel ? (
                  <Alert severity="warning">
                    任务默认模型当前不在可用模型列表中，请先手动选择本次动作模型。
                  </Alert>
                ) : null}
                <Typography variant="caption" color="text.secondary">
                  {formatModelRefreshStatus(modelRefresh)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  默认沿用当前任务模型；开始执行和继续创作时都可临时切换。恢复动作请在恢复面板中单独选择模型。
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  创作模型：{workspace.meta.creative_model_id || workspace.meta.default_model_id || workspace.meta.model_id || "未设置"}
                  {workspace.meta.last_action_model_id
                    ? ` · 最近一次创作动作模型：${workspace.meta.last_action_model_id}${formatActionKindLabel(workspace.meta.last_action_kind) ? `（${formatActionKindLabel(workspace.meta.last_action_kind)}）` : ""}`
                    : ""}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  审核模型：{formatWorkspaceReviewModel(workspace)}
                </Typography>
              </Stack>
            </Box>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <Chip
                label={`类型: ${formatTaskTypeLabel({
                  creativeMode: workspace.meta.creative_mode,
                  novelSize: workspace.meta.novel_size,
                  mode: workspace.meta.mode,
                })}`}
                size="small"
                variant="outlined"
              />
              {workspace.request_preview?.genre && <Chip label={`题材: ${workspace.request_preview.genre}`} size="small" variant="outlined" />}
              {workspace.request_preview?.style && <Chip label={`风格: ${workspace.request_preview.style}`} size="small" variant="outlined" />}
              {workspace.available_tabs?.map((tab) => (
                <Chip key={tab} label={tab} size="small" variant="outlined" />
              ))}
              <Chip
                label={`自动审核：${workspace.meta.auto_review ? "开启" : "关闭"}`}
                size="small"
                variant="outlined"
              />
              <Chip
                label={`创作模型：${workspace.meta.creative_model_id || workspace.meta.default_model_id || workspace.meta.model_id || "未设置"}`}
                size="small"
                variant="outlined"
              />
              <Chip
                label={`审核模型：${formatWorkspaceReviewModel(workspace)}`}
                size="small"
                variant="outlined"
              />
            </Stack>
            {workspace.active_trace_summary && (
              <Typography variant="body2" color="text.secondary">
                执行摘要：{workspace.active_trace_summary}
              </Typography>
            )}

            {workspace.meta.status === "ready_for_batch" && novelProgress && (
              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  backgroundColor: "rgba(39, 100, 81, 0.03)",
                }}
              >
                <Stack spacing={2}>
                  <Typography variant="subtitle1">继续创作</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip label={`目标章节：${novelProgress.target_chapter_count ?? "未设定"}`} size="small" variant="outlined" />
                    <Chip label={`规划章节：${novelProgress.planned_chapter_count ?? "未设定"}`} size="small" variant="outlined" />
                    <Chip label={`已完成：${novelProgress.completed_chapter_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`下一章：${novelProgress.next_chapter_number ?? 1}`} size="small" variant="outlined" />
                    <Chip label={`剩余：${novelProgress.remaining_chapter_count ?? 0}`} size="small" variant="outlined" />
                  </Stack>
                  <TextField
                    label="本次创建章节数"
                    type="number"
                    value={requestedChapterCount}
                    onChange={(event) => setRequestedChapterCount(Math.max(1, Number(event.target.value) || 1))}
                    inputProps={{ min: 1, step: 1 }}
                    helperText={`默认批次值：${novelProgress.default_batch_size ?? 3}`}
                    sx={{ maxWidth: 280 }}
                  />
                </Stack>
              </Box>
            )}

            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                border: "1px solid",
                borderColor: "divider",
                backgroundColor: "rgba(29, 42, 39, 0.03)",
              }}
            >
              <Stack spacing={1.5}>
                <Typography variant="subtitle1">上下文状态</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip size="small" variant="outlined" label={formatContextWindowLabel(modelCapabilities)} />
                  <Chip size="small" variant="outlined" label={formatContextCacheLabel(modelCapabilities, contextStatus)} />
                  <Chip size="small" variant="outlined" label={formatResponseCacheLabel(modelCapabilities, responseCacheStatus)} />
                  <Chip size="small" variant="outlined" label={formatCompressionLabel(modelCapabilities, contextStatus)} />
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  阶段：{contextStatus?.stage || workspace.meta.current_stage || "未上报"}
                  {" · "}
                  状态：{contextStatus?.status || "暂未上报"}
                  {" · "}
                  当前输入：{formatTokenCount(contextStatus?.input_tokens || contextStatus?.current_tokens)} tokens
                  {" · "}
                  输入上限：{formatTokenCount(
                    contextStatus?.max_input_tokens || modelCapabilities?.context_window?.max_input_tokens,
                  )}{" "}
                  tokens
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {contextStatus?.summary || contextStatus?.compression_summary || "后端暂未返回上下文摘要或缓存/压缩细节。"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {responseCacheStatus
                    ? [
                        responseCacheStatus.summary || "响应缓存状态已返回。",
                        typeof responseCacheStatus.history_count === "number"
                          ? `历史消息：${responseCacheStatus.history_count} 条`
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : "响应缓存：当前未上报独立状态。"}
                </Typography>
              </Stack>
            </Box>
          </Stack>
          </Collapse>
          </Stack>
        </CardContent>
      </Card>

      {/* Tab 区域 */}
      <Card>
        <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Tabs
              value={activeTab}
              onChange={(_, v) => setActiveTab(v)}
              variant="scrollable"
              scrollButtons
              allowScrollButtonsMobile
              aria-label="任务运行详情标签页"
            >
              <Tab label={`实时日志 (${systemStages.length})`} />
              <Tab label={`章节进度 (${chapterProgress.length})`} />
              <Tab label={`Supervisor (${workspace.supervisor_plan?.subtasks.length ?? 0})`} />
              <Tab label="任务详情" />
              <Tab label="调试" />
            </Tabs>
            {activeTab === 0 && (
              <Tooltip title={logTabExpanded ? "收起日志" : "展开日志"}>
                <IconButton
                  size="small"
                  onClick={() => setLogTabExpanded((prev) => !prev)}
                  sx={{ mr: 1, transform: logTabExpanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
              </Tooltip>
            )}
            {activeTab === 1 && (
              <Tooltip title={tab1Expanded ? "收起章节进度" : "展开章节进度"}>
                <IconButton
                  size="small"
                  onClick={() => setTab1Expanded((prev) => !prev)}
                  sx={{ mr: 1, transform: tab1Expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
              </Tooltip>
            )}
            {activeTab === 2 && (
              <Tooltip title={tab2Expanded ? "收起 Supervisor" : "展开 Supervisor"}>
                <IconButton
                  size="small"
                  onClick={() => setTab2Expanded((prev) => !prev)}
                  sx={{ mr: 1, transform: tab2Expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
              </Tooltip>
            )}
            {activeTab === 3 && (
              <Tooltip title={tab3Expanded ? "收起任务详情" : "展开任务详情"}>
                <IconButton
                  size="small"
                  onClick={() => setTab3Expanded((prev) => !prev)}
                  sx={{ mr: 1, transform: tab3Expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
              </Tooltip>
            )}
            {activeTab === 4 && (
              <Tooltip title={tab4Expanded ? "收起调试" : "展开调试"}>
                <IconButton
                  size="small"
                  onClick={() => setTab4Expanded((prev) => !prev)}
                  sx={{ mr: 1, transform: tab4Expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                >
                  <ExpandIcon />
                </IconButton>
              </Tooltip>
            )}
          </Stack>
        </Box>
        <CardContent>
          {/* Tab 0: 实时日志 */}
          {activeTab === 0 && (
            <Collapse in={logTabExpanded}>
              <Stack spacing={3}>
              {/* 思考链区域 */}
              {thinkingGroups.length > 0 && (
                <Box>
                  <Typography variant="h6" sx={{ mb: 1.5, display: "flex", alignItems: "center", gap: 1 }}>
                    <ThinkIcon sx={{ fontSize: 20, color: "primary.main" }} />
                    模型思考过程
                  </Typography>
                  {thinkingGroups.map((group) => {
                    const key = group.unitId;
                    const isOpen = expandedThinking[key] ?? false;
                    const isRunning = group.isActive && ["planning", "drafting", "verification"].includes(workspace.meta.status);
                    return (
                      <Box
                        key={key}
                        sx={{
                          mb: 1.5,
                          borderRadius: 2,
                          border: "1px solid",
                          borderColor: isRunning ? "primary.main" : "divider",
                          bgcolor: isRunning ? "rgba(39, 100, 81, 0.03)" : "background.paper",
                          overflow: "hidden",
                        }}
                      >
                        <Box
                          onClick={() => setExpandedThinking((prev) => ({ ...prev, [key]: !prev[key] }))}
                          sx={{
                            display: "flex",
                            alignItems: "center",
                            gap: 1,
                            px: 2,
                            py: 1,
                            cursor: "pointer",
                            "&:hover": { bgcolor: "rgba(0,0,0,0.02)" },
                            userSelect: "none",
                          }}
                        >
                          <ThinkIcon sx={{ fontSize: 18, color: isRunning ? "primary.main" : "text.secondary" }} />
                          <Typography variant="body2" sx={{ flex: 1, fontWeight: isRunning ? 600 : 400 }}>
                            {isRunning ? "正在思考..." : `思考过程 · ${group.stage} · ${group.unitId}`}
                          </Typography>
                          {isRunning && <CircularProgress size={14} />}
                          {group.model && (
                            <Typography variant="caption" color="text.secondary">
                              {group.model}
                            </Typography>
                          )}
                          <Typography variant="caption" color="text.secondary">
                            {group.content.length} 字
                          </Typography>
                          {group.finishReason && (
                            <Chip size="small" variant="outlined" label={`完成: ${group.finishReason}`} />
                          )}
                          {isOpen ? <CollapseIcon sx={{ fontSize: 16 }} /> : <ExpandIcon sx={{ fontSize: 16 }} />}
                        </Box>
                        <Collapse in={isOpen}>
                          <Box
                            sx={{
                              px: 2,
                              py: 1.5,
                              maxHeight: 600,
                              overflowY: "auto",
                              fontSize: "0.82rem",
                              color: "text.secondary",
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-word",
                              lineHeight: 1.7,
                              fontFamily: "monospace",
                              bgcolor: "rgba(39, 100, 81, 0.02)",
                              borderTop: "1px dashed rgba(39, 100, 81, 0.1)",
                            }}
                          >
                            {group.content}
                          </Box>
                        </Collapse>
                      </Box>
                    );
                  })}
                  <Divider sx={{ my: 1 }} />
                </Box>
              )}
              <Box>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                  {streamState}
                </Typography>
                <List dense>
                  {systemStages.length ? (
                    systemStages.map((event) => (
                      <div key={event.event_id}>
                        <ListItem disableGutters alignItems="flex-start">
                          <ListItemText
                            primary={event.message}
                            secondary={
                              [
                                `${event.stage} · ${event.event_type} · ${formatEventTime(event.created_at)}`,
                                formatEventRef(event),
                              ]
                                .filter(Boolean)
                                .join("\n")
                            }
                            secondaryTypographyProps={{ sx: { whiteSpace: "pre-line" } }}
                          />
                        </ListItem>
                        <Divider component="li" />
                      </div>
                    ))
                  ) : (
                    <ListItem disableGutters>
                      <ListItemText primary="暂无系统阶段事件" />
                    </ListItem>
                  )}
                </List>
              </Box>
              <Divider />
              <Box>
                <Typography variant="h6" sx={{ mb: 1.5 }}>过程摘要流</Typography>
                <List dense>
                  {summaryStream.length ? (
                    summaryStream.map((item) => (
                      <div key={item.id}>
                        <ListItem disableGutters alignItems="flex-start">
                          <Avatar
                            sx={{
                              width: 32,
                              height: 32,
                              mr: 1.5,
                              bgcolor: "rgba(39, 100, 81, 0.12)",
                              color: "primary.main",
                              fontSize: 14,
                            }}
                          >
                            摘
                          </Avatar>
                          <ListItemText primary={item.title} secondary={item.subtitle} />
                        </ListItem>
                        <Divider component="li" />
                      </div>
                    ))
                  ) : (
                    <ListItem disableGutters>
                      <ListItemText primary="暂无过程摘要" />
                    </ListItem>
                  )}
                </List>
              </Box>
            </Stack>
          </Collapse>
          )}

          {/* Tab 1: 章节进度 */}
          {activeTab === 1 && (
            <Collapse in={tab1Expanded}>
              <List dense>
                {chapterProgress.length ? (
                  chapterProgress.map((chapter) => (
                    <div key={chapter.number}>
                      <ListItem disableGutters alignItems="flex-start">
                        <ListItemButton
                          onClick={() => void handleChapterClick(chapter.number, chapter.title)}
                          sx={{ py: 1 }}
                        >
                          <ListItemText
                            primary={
                              <Stack direction="row" spacing={1} alignItems="center">
                                <Typography>{`第 ${chapter.number} 章 · ${chapter.title}`}</Typography>
                                <Chip
                                  label={chapter.status}
                                  size="small"
                                  color={chapter.status === "已完成" ? "success" : "default"}
                                />
                              </Stack>
                            }
                            secondary={
                              [
                                formatEventTime(chapter.updatedAt),
                                chapter.summary || "",
                              ]
                                .filter(Boolean)
                                .join(" · ")
                            }
                            secondaryTypographyProps={{ sx: { whiteSpace: "pre-line" } }}
                          />
                        </ListItemButton>
                      </ListItem>
                      <LinearProgress
                        variant="determinate"
                        value={chapter.progress}
                        sx={{ mb: 1.5, height: 8, borderRadius: 999 }}
                      />
                      <Divider component="li" />
                    </div>
                  ))
                ) : (
                  <ListItem disableGutters>
                    <ListItemText primary="当前还没有章节级进度事件" />
                  </ListItem>
                )}
              </List>
            </Collapse>
          )}

          {/* Tab 2: Supervisor */}
          {activeTab === 2 && (
            <Collapse in={tab2Expanded}>
              <Stack spacing={2}>
                {!workspace.supervisor_plan ? (
                  <Alert severity="info">当前任务还没有可展示的 Supervisor 规划。</Alert>
                ) : (
                  <>
                    <Box>
                      <Typography variant="h6" sx={{ mb: 1 }}>
                        规划版本：{workspace.supervisor_plan.planner_version}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        子任务：{workspace.supervisor_plan.subtasks.length} 个
                        {" · "}
                        依赖边：{workspace.supervisor_plan.dependencies.length} 条
                        {" · "}
                        Agent 运行记录：{workspace.agent_runs?.length ?? 0} 条
                      </Typography>
                    </Box>

                    <List dense>
                      {workspace.supervisor_plan.subtasks.map((subtask) => {
                        const status = resolveSupervisorStatus(subtask);
                        const incoming = countIncomingDependencies(workspace, subtask.id);
                        const outgoing = countOutgoingDependencies(workspace, subtask.id);
                        return (
                          <div key={subtask.id}>
                            <ListItem disableGutters alignItems="flex-start">
                              <ListItemText
                                primary={
                                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                                    <Typography>{subtask.title}</Typography>
                                    <Chip size="small" color={status.color} label={status.label} />
                                    <Chip size="small" variant="outlined" label={subtask.kind} />
                                  </Stack>
                                }
                                secondary={
                                  [
                                    `依赖上游 ${incoming} 个`,
                                    `下游 ${outgoing} 个`,
                                    subtask.assigned_agent ? `指派: ${subtask.assigned_agent}` : "",
                                  ]
                                    .filter(Boolean)
                                    .join(" · ")
                                }
                              />
                            </ListItem>
                            <Divider component="li" />
                          </div>
                        );
                      })}
                    </List>

                    {workspace.agent_runs?.length ? (
                      <Box>
                        <Typography variant="subtitle1" sx={{ mb: 1 }}>
                          Agent 运行记录
                        </Typography>
                        <List dense>
                          {workspace.agent_runs.map((run) => (
                            <div key={run.id}>
                              <ListItem disableGutters>
                                <ListItemText
                                  primary={`${run.agent_name} · ${run.role}`}
                                  secondary={`状态：${run.status} · 子任务：${run.subtask_id}`}
                                />
                              </ListItem>
                              <Divider component="li" />
                            </div>
                          ))}
                        </List>
                      </Box>
                    ) : null}
                  </>
                )}
              </Stack>
            </Collapse>
          )}

          {/* Tab 3: 任务详情 */}
          {activeTab === 3 && (
            <Collapse in={tab3Expanded}>
              <Stack spacing={2}>
                <Stack direction="row" spacing={2}>
                  <Typography variant="body2" color="text.secondary">
                    Task ID：{workspace.meta.task_id}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    任务默认模型：
                    {workspace.request_preview?.default_model_id ||
                      workspace.meta.default_model_id ||
                      workspace.request_preview?.model_id ||
                      workspace.meta.model_id ||
                      "默认模型"}
                    {workspace.request_preview?.last_action_model_id
                      ? ` · 最近一次动作模型：${workspace.request_preview.last_action_model_id}${formatActionKindLabel(workspace.request_preview.last_action_kind) ? `（${formatActionKindLabel(workspace.request_preview.last_action_kind)}）` : ""}`
                      : ""}
                  </Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {formatContextWindowLabel(modelCapabilities)}
                  {" · "}
                  {formatContextCacheLabel(modelCapabilities, contextStatus)}
                  {" · "}
                  {formatResponseCacheLabel(modelCapabilities, responseCacheStatus)}
                  {" · "}
                  {formatCompressionLabel(modelCapabilities, contextStatus)}
                </Typography>
                {typeof (workspace.request_preview?.chapter_word_min ?? workspace.meta.chapter_word_min) === "number" && (
                  <Typography variant="body2" color="text.secondary">
                    单章字数下限：
                    {workspace.request_preview?.chapter_word_min ?? workspace.meta.chapter_word_min}
                    {" · "}读者：{workspace.request_preview?.audience || "未指定"}
                  </Typography>
                )}
                {workspace.meta.current_unit && (
                  <Typography variant="body2" color="text.secondary">
                    当前单元：{workspace.meta.current_unit}
                  </Typography>
                )}
                {workspace.meta.updated_at && (
                  <Typography variant="body2" color="text.secondary">
                    最近更新：{new Date(workspace.meta.updated_at).toLocaleString()}
                  </Typography>
                )}
                <Typography variant="body2" color="text.secondary">
                  上下文缓存键：{contextStatus?.cache_key || "未上报"}
                  {" · "}
                  上下文缓存范围：{contextStatus?.cache_scope || "未上报"}
                  {" · "}
                  缓存片段：{typeof contextStatus?.cached_segments === "number" ? contextStatus.cached_segments : "未上报"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  响应缓存键：{responseCacheStatus?.cache_key || "未上报"}
                  {" · "}
                  响应缓存范围：{responseCacheStatus?.cache_scope || "未上报"}
                  {" · "}
                  历史消息：{typeof responseCacheStatus?.history_count === "number" ? responseCacheStatus.history_count : "未上报"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {workspace.meta.summary || "暂无摘要"}
                </Typography>
              </Stack>
            </Collapse>
          )}

          {/* Tab 4: 调试 */}
          {activeTab === 4 && (
            <Collapse in={tab4Expanded}>
              <DebugPanel
                workspace={workspace}
                streamState={streamState}
                streamPath={debugStreamPath}
                onRefresh={() => void refreshWorkspace()}
                onOpenRecovery={handleOpenRecoveryDialog}
              />
            </Collapse>
          )}
        </CardContent>
      </Card>
      <RecoveryDialog
        open={recoveryDialogOpen}
        recovery={workspace}
        models={selectableModels}
        selectedAction={selectedRecoveryAction}
        selectedModelId={recoveryModelId}
        defaultModelId={defaultRecoveryModelId}
        submitting={running}
        onActionChange={(action) => {
          setSelectedRecoveryAction(action);
          setRecoveryModelId("");
        }}
        onModelChange={setRecoveryModelId}
        onCancel={() => setRecoveryDialogOpen(false)}
        onConfirm={() =>
          void handleRecover({
            recovery_mode: selectedRecoveryAction,
            model_id: recoveryModelId,
          })
        }
      />
      {/* 章节正文弹窗 */}
      <Dialog
        open={chapterDialogOpen}
        onClose={() => setChapterDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        {selectedChapter && (
          <>
            <DialogTitle>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h5">
                  第 {selectedChapter.number} 章：{selectedChapter.title}
                </Typography>
                <IconButton onClick={() => setChapterDialogOpen(false)}>
                  <CloseIcon />
                </IconButton>
              </Stack>
              {selectedChapter.summary && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {selectedChapter.summary}
                </Typography>
              )}
            </DialogTitle>
            <DialogContent dividers>
              <Typography
                component="pre"
                sx={{
                  fontFamily: "inherit",
                  fontSize: 15,
                  lineHeight: 1.8,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {selectedChapter.content}
              </Typography>
            </DialogContent>
          </>
        )}
      </Dialog>
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMsg}
      />
    </Stack>
    </Container>
  );
}
