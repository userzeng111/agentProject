"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
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
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
  Close as CloseIcon,
  Psychology as ThinkIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
} from "@mui/icons-material";
import { continueTask, getApiBase, getCurrentChapters, getModelCatalog, getWorkspace, normalizeModelOptions, recoverTask, runTask } from "@/lib/api";
import RecoveryDialog from "@/features/task-recovery/recovery-dialog";
import {
  derivePrimaryRecoveryAction,
  filterRecoveryModels,
  resolveRecoveryPreview,
} from "@/features/task-recovery/recovery-state.mjs";
import { formatModelRefreshStatus, resolveSelectionAfterRefresh } from "@/features/task-models/model-refresh-state.mjs";
import { selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { resultHref, reviewHref } from "@/lib/task-routes";
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

const WORKFLOW_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "运行", icon: <PlayIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

function getStepIndex(status: TaskStatus): number {
  if (status === "completed") return 4;
  if (
    status === "waiting_outline_review" ||
    status === "waiting_chapter_review" ||
    status === "waiting_verification_review" ||
    status === "ready_for_batch" ||
    status === "drafting" ||
    status === "assembling"
  )
    return 2;
  if (status === "planning" || status === "sources_ingested" || status === "waiting_manual_action") return 1;
  return 0;
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
    workspace?.request_preview?.default_model_id ||
    workspace?.meta.default_model_id ||
    workspace?.request_preview?.model_id ||
    workspace?.meta.model_id ||
    ""
  );
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

function buildChapterProgress(events: WorkspaceEvent[]) {
  const chapterMap = new Map<
    number,
    {
      number: number;
      title: string;
      status: string;
      progress: number;
      summary?: string;
      updatedAt: string;
    }
  >();

  events
    .filter((event) => event.event_type.startsWith("chapter."))
    .forEach((event) => {
      const chapterNumber = event.payload?.chapter_number;
      if (typeof chapterNumber !== "number") {
        return;
      }
      const current = chapterMap.get(chapterNumber);
      const title = event.payload?.chapter_title || current?.title || event.unit_id || `第 ${chapterNumber} 章`;
      chapterMap.set(chapterNumber, {
        number: chapterNumber,
        title,
        status: event.event_type === "chapter.saved" ? "已完成" : "生成中",
        progress: event.event_type === "chapter.saved" ? 100 : 56,
        summary: event.payload?.chapter_summary || current?.summary,
        updatedAt: event.created_at,
      });
    });

  return Array.from(chapterMap.values()).sort((left, right) => left.number - right.number);
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

interface ThinkingGroup {
  unitId: string;
  stage: string;
  content: string;
  lastUpdatedAt: string;
  isActive: boolean;
}

function buildThinkingGroups(events: WorkspaceEvent[]): ThinkingGroup[] {
  const thinkingEvents = events.filter((event) => event.event_type === "model.thinking");
  if (!thinkingEvents.length) return [];

  const groupMap = new Map<string, ThinkingGroup>();
  for (const event of thinkingEvents) {
    const key = event.unit_id || "default";
    const existing = groupMap.get(key);
    const chunk = event.payload?.reasoning_chunk || "";
    const isLast = event === thinkingEvents[thinkingEvents.length - 1];
    groupMap.set(key, {
      unitId: key,
      stage: event.stage || "",
      content: (existing?.content || "") + chunk,
      lastUpdatedAt: event.created_at,
      isActive: isLast,
    });
  }

  // 只保留最后一个活跃的思考组（正在思考的）
  const groups = Array.from(groupMap.values());
  const lastGroup = groups[groups.length - 1];
  if (lastGroup) {
    lastGroup.isActive = true;
  }
  return groups;
}

export default function TaskRunClient({ taskId }: { taskId?: string }) {
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
  const [requestedChapterCount, setRequestedChapterCount] = useState(3);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({ loading: false, error: "" });
  const [actionModelId, setActionModelId] = useState("");
  const [recoveryDialogOpen, setRecoveryDialogOpen] = useState(false);
  const [selectedRecoveryAction, setSelectedRecoveryAction] = useState<RecoveryMode>("recover_to_stable");
  const [recoveryModelId, setRecoveryModelId] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const continueRequestIdRef = useRef<string | null>(null);
  const currentActionModelIdRef = useRef("");
  const currentTaskModelIdRef = useRef("");
  const currentModelOptionsRef = useRef<ModelOption[]>([]);

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
    setActionModelId("");
    setModelRefresh({ loading: false, error: "" });
    setRecoveryDialogOpen(false);
    setSelectedRecoveryAction("recover_to_stable");
    setRecoveryModelId("");
  }, [resolvedTaskId]);

  const selectableModels: ModelOption[] = selectNovelTaskModels(models);
  const resolvedActionModelId = selectableModels.some((item) => item.id === actionModelId)
    ? actionModelId
    : "";
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
    if (currentTaskModelId && selectableModels.some((item) => item.id === currentTaskModelId)) {
      setActionModelId(currentTaskModelId);
      return;
    }
    setActionModelId("");
  }, [actionModelId, currentTaskModelId, selectableModels]);

  const hasValidActionModel = Boolean(resolvedActionModelId);

  function handleActionModelChange(nextModelId: string) {
    setActionModelId(nextModelId);
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

    let disposed = false;
    let source: EventSource | null = null;
    const candidatePaths = streamPathCandidates(resolvedTaskId);
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 3;
    const RECONNECT_DELAY = 2000;

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
        void refreshWorkspace();
      };
      source.addEventListener("snapshot", handleRefresh);
      source.addEventListener("task.event", handleRefresh);
      source.addEventListener("task.done", handleRefresh);

      source.onerror = () => {
        source?.close();
        if (disposed) {
          return;
        }
        if (!opened) {
          tryConnect(index + 1);
          return;
        }
        if (reconnectAttempts < MAX_RECONNECT) {
          reconnectAttempts += 1;
          setStreamState(`事件流已断开，${RECONNECT_DELAY / 1000}秒后第${reconnectAttempts}次重连...`);
          setTimeout(() => {
            if (!disposed) {
              tryConnect(0);
            }
          }, RECONNECT_DELAY);
          return;
        }
        setStreamState("事件流已断开，当前使用手动刷新");
      };
    };

    tryConnect(0);

    return () => {
      disposed = true;
      source?.close();
      eventSourceRef.current = null;
    };
  }, [resolvedTaskId, refreshWorkspace]);

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
      const requestId = continueRequestIdRef.current ?? crypto.randomUUID();
      continueRequestIdRef.current = requestId;
      await continueTask(resolvedTaskId, {
        requested_chapter_count: requestedChapterCount,
        continue_request_id: requestId,
        model_id: resolvedActionModelId || undefined,
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
          <Alert severity="error">{error || "读取工作台失败"}</Alert>
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
  const chapterProgress = buildChapterProgress(workspace.recent_events);
  const summaryStream = buildSummaryStream(workspace.recent_events, workspace.active_trace_summary);
  const thinkingGroups = buildThinkingGroups(workspace.recent_events);
  const currentStep = getStepIndex(workspace.meta.status);
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

      {/* 步骤指示器 */}
      <Card className="glass-card">
        <CardContent sx={{ py: 2 }}>
          <Stack direction="row" justifyContent="center" spacing={0} sx={{ width: "100%" }}>
            {WORKFLOW_STEPS.map((step, index) => {
              const isDone = index < currentStep;
              const isActive = index === currentStep;
              return (
                <Box
                  key={step.label}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    flex: index < WORKFLOW_STEPS.length - 1 ? 1 : 0,
                    justifyContent: "center",
                  }}
                >
                  <Stack spacing={0.5} alignItems="center" sx={{ minWidth: 64 }}>
                    <Box
                      sx={{
                        width: 36,
                        height: 36,
                        borderRadius: "50%",
                        display: "grid",
                        placeItems: "center",
                        backgroundColor: isDone ? "success.main" : isActive ? "primary.main" : "rgba(29,42,39,0.08)",
                        color: "#fff",
                        transition: "all 0.3s",
                      }}
                    >
                      {isDone ? <CheckCircleIcon fontSize="small" /> : step.icon}
                    </Box>
                    <Typography
                      variant="caption"
                      sx={{
                        fontWeight: isActive ? 600 : 400,
                        color: isActive ? "primary.main" : isDone ? "success.main" : "text.secondary",
                      }}
                    >
                      {step.label}
                    </Typography>
                  </Stack>
                  {index < WORKFLOW_STEPS.length - 1 && (
                    <Box
                      sx={{
                        flex: 1,
                        height: 2,
                        mx: 1,
                        mt: -2,
                        backgroundColor: isDone ? "success.main" : "rgba(29,42,39,0.08)",
                        transition: "all 0.3s",
                        borderRadius: 1,
                      }}
                    />
                  )}
                </Box>
              );
            })}
          </Stack>
        </CardContent>
      </Card>

      {error ? <Alert severity="error">{error}</Alert> : null}
      {!error && workspace.state_reconciled ? (
        <Alert severity="info">
          {workspace.reconciliation_summary || "当前页面已自动校正到最新稳定状态。"}
        </Alert>
      ) : null}
      {!error && workspace.meta.status === "waiting_manual_action" && workspace.meta.error_message ? (
        <Alert severity="warning">
          <Stack spacing={1}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              当前任务需要人工处理
            </Typography>
            <Typography variant="body2">{workspace.meta.error_message}</Typography>
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

      {/* 请求摘要卡片 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}>
              <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                请求摘要
              </Typography>
              <Stack direction="row" spacing={1}>
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
                    进入审核
                  </Button>
                )}
                {workspace.meta.status === "completed" && (
                  <Button component={Link} href={resultHref(workspace.meta.task_id)} variant="contained" size="small">
                    查看结果
                  </Button>
                )}
                <Button variant="outlined" onClick={() => void refreshWorkspace()} size="small">
                  刷新
                </Button>
              </Stack>
            </Stack>
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
                  <Typography variant="subtitle1">本次动作模型</Typography>
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
                    <em>请选择本次动作模型</em>
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
                  任务默认模型：{workspace.meta.default_model_id || workspace.meta.model_id || "未设置"}
                  {workspace.meta.last_action_model_id
                    ? ` · 最近一次动作模型：${workspace.meta.last_action_model_id}${formatActionKindLabel(workspace.meta.last_action_kind) ? `（${formatActionKindLabel(workspace.meta.last_action_kind)}）` : ""}`
                    : ""}
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
        </CardContent>
      </Card>

      {/* 进度条 */}
      <Box>
        <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {workspace.meta.current_stage || "初始化中"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {workspace.meta.progress}%
          </Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={workspace.meta.progress}
          sx={{ height: 8, borderRadius: 999 }}
        />
      </Box>

      {/* Tab 区域 */}
      <Card>
        <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)}>
            <Tab label={`实时日志 (${systemStages.length})`} />
            <Tab label={`章节进度 (${chapterProgress.length})`} />
            <Tab label={`Supervisor (${workspace.supervisor_plan?.subtasks.length ?? 0})`} />
            <Tab label="任务详情" />
          </Tabs>
        </Box>
        <CardContent>
          {/* Tab 0: 实时日志 */}
          {activeTab === 0 && (
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
                          <Typography variant="caption" color="text.secondary">
                            {group.content.length} 字
                          </Typography>
                          {isOpen ? <CollapseIcon sx={{ fontSize: 16 }} /> : <ExpandIcon sx={{ fontSize: 16 }} />}
                        </Box>
                        <Collapse in={isOpen}>
                          <Box
                            sx={{
                              px: 2,
                              py: 1.5,
                              maxHeight: 300,
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
          )}

          {/* Tab 1: 章节进度 */}
          {activeTab === 1 && (
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
          )}

          {/* Tab 2: Supervisor */}
          {activeTab === 2 && (
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
          )}

          {/* Tab 3: 任务详情 */}
          {activeTab === 3 && (
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
    </Stack>
    </Container>
  );
}
